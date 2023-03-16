import asyncio
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Iterable, Union

from dateutil import parser
from loguru import logger
from schedule import CancelJob, Scheduler

from ...utils import to_iterable
from ..tele import ClientsSession


@dataclass
class MessageSchedule:
    message: str
    at: Union[Iterable[Union[str, time]], Union[str, time]] = ("0:00", "23:59")
    every: str = "days"
    possibility: float = 1.0
    only: str = None


class Messager:
    name = __name__
    chat_name = None
    messages = []

    def __init__(self, account, loop, scheduler: Scheduler, nofail=True, proxy=None):
        self.account = account
        self.loop = loop
        self.scheduler = scheduler
        self.nofail = nofail
        self.proxy = proxy
        self.log = logger.bind(scheme="telemessager", name=self.name)

    def start(self):
        for m in self.messages:
            if isinstance(m, MessageSchedule):
                self.schedule(m.message, m.at, m.every, m.possibility, m.only)
        self.next_info()

    async def _send(self, *args, **kw):
        try:
            return await self.send(*args, **kw)
        except OSError as e:
            self.log.info(f'出现错误: "{e}", 忽略.')
        except Exception as e:
            if self.nofail:
                self.log.opt(exception=e).warning(f"发生错误:")
            else:
                raise

    async def send(self, message, reschedule, possibility=1.0, only=None):
        if random.random() >= possibility:
            return self.log.info(f"由于概率设置, 本次发送被跳过.")
        if only:
            today = datetime.today()
            if only.startswith("weekdays") and today.weekday() > 4:
                return self.log.info(f"由于非周末, 本次发送被跳过.")
            if only.startswith("weekends") and today.weekday() < 5:
                return self.log.info(f"由于非工作日, 本次发送被跳过.")
        async with ClientsSession([self.account], proxy=self.proxy) as clients:
            async for tg in clients:
                chat = await tg.get_chat(self.chat_name)
                self.log.bind(username=tg.me.first_name).info(
                    f'向聊天 "{chat.title or chat.first_name}" 发送: {message}'
                )
                await tg.send_message(self.chat_name, message)
            reschedule()
            self.next_info()
            if self.scheduler.next_run - datetime.now() < timedelta(minutes=1):
                await asyncio.sleep(60)
            return CancelJob

    def next_info(self):
        self.log.info(f"下一次发送将在 [blue]{self.scheduler.next_run.strftime('%m-%d %H:%M:%S %p')}[/] 进行.")

    @staticmethod
    def random_time(start_time, end_time):
        start_datetime = datetime.combine(date.today(), start_time)
        end_datetime = datetime.combine(date.today(), end_time)
        if end_datetime < start_datetime:
            end_datetime += timedelta(days=1)
        time_diff_seconds = (end_datetime - start_datetime).seconds
        random_seconds = random.randint(0, time_diff_seconds)
        random_time = (start_datetime + timedelta(seconds=random_seconds)).time()
        return random_time

    def schedule(self, message, at, every, possibility, only):
        def reschedule():
            if not at:
                return
            _at = [a if isinstance(a, time) else parser.parse(a).time() for a in to_iterable(at)]
            if len(_at) == 1:
                t = _at[0]
            elif len(_at) == 2:
                t = self.random_time(*_at)
            else:
                t = random.choice(_at)
            if isinstance(message, Iterable):
                m = random.choice(message)
            else:
                m = message
            _every = every.split()
            if len(_every) > 1:
                n, *_every = _every
            else:
                n = 1
            getattr(self.scheduler.every(int(n)), _every[0]).at(t.strftime("%H:%M:%S")).do(
                self.loop.create_task, self._send(m, reschedule, possibility, only)
            )

        reschedule()
