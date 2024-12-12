import asyncio
import signal
import uuid
from abc import ABC, abstractmethod
from asyncio import Future
from asyncio import Queue as AsyncQueue
from dataclasses import dataclass
from enum import Enum, auto
from multiprocessing import Condition, Event, Process, Queue
from queue import Empty
from types import TracebackType
from typing import Optional, Protocol

from obsidian_index.logger import logging


class ConditionLike(Protocol):
    def __enter__(self) -> bool: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
        /,
    ): ...

    def wait(self, timeout: float | None = None) -> bool: ...

    def wait_for(self, predicate, timeout: float | None = None) -> bool: ...

    def notify(self): ...

    def notify_all(self): ...


class EventLike(Protocol):
    def is_set(self) -> bool: ...

    def set(self) -> None: ...


class WorkerState(Enum):
    INITIALIZING = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()


@dataclass
class WorkerControl:
    """
    Container for worker control mechanisms.
    """

    input_queue: Queue
    output_queue: Queue
    state_condition: ConditionLike
    work_available: ConditionLike
    stop_event: EventLike


@dataclass
class Message[I]:
    """
    Message wrapper with correlation ID.
    """

    id: str
    payload: I


@dataclass
class Response[O]:
    """
    Response wrapper with correlation ID.
    """

    id: str
    payload: O


class BaseWorker[I, O](ABC):
    """
    Base class for worker logic.
    """

    def __init__(self):
        self._state = WorkerState.INITIALIZING
        self._control: Optional[WorkerControl] = None

    def init_control(self, control: WorkerControl) -> None:
        """Initialize control mechanisms"""
        self._control = control

    @abstractmethod
    def initialize(self):
        """Initialize the worker"""
        pass

    @property
    def state(self) -> WorkerState:
        return self._state

    def _set_state(self, new_state: WorkerState) -> None:
        assert self._control is not None
        with self._control.state_condition:
            self._state = new_state
            self._control.state_condition.notify_all()

    def run_worker(self) -> None:
        """Entry point for the worker process"""
        # Set up signal handling
        signal.signal(signal.SIGTERM, lambda sig, frame: self.stop())
        # Initialize the worker
        self.initialize()
        # Run the main loop
        self.run_loop()

    def run_loop(self) -> None:
        """Main processing loop"""
        assert self._control is not None
        self._set_state(WorkerState.RUNNING)

        try:
            while not self._control.stop_event.is_set():
                # Wait for work with the condition
                with self._control.work_available:
                    while (
                        not self._control.stop_event.is_set()
                        and self._control.input_queue.empty()
                        and not self.default_work_available()
                    ):
                        self._control.work_available.wait()

                    if self._control.stop_event.is_set():
                        break

                    msg: Message[I] | None
                    try:
                        msg = self._control.input_queue.get_nowait()
                    except Empty:
                        msg = None

                if msg:
                    result = self.process_message(msg.payload)
                    response = Response(id=msg.id, payload=result)
                    self._control.output_queue.put(response)
                elif self.default_work_available():
                    self.default_work()

        except Exception as e:
            logging.exception("Error in worker process")
            self._control.output_queue.put(e)
        finally:
            self._cleanup()

    def stop(self) -> None:
        """Handle stop request"""
        assert self._control is not None
        self._set_state(WorkerState.STOPPING)
        self._control.stop_event.set()
        # Wake up the worker if it's waiting
        with self._control.work_available:
            self._control.work_available.notify()

    def _cleanup(self) -> None:
        """Cleanup before exit"""
        self._set_state(WorkerState.STOPPED)

    @abstractmethod
    def process_message(self, message: I) -> O:
        """Process a single input message and return result"""
        pass

    def default_work_available(self) -> bool:
        """
        If there's no work available, do this instead.
        """
        return False

    def default_work(self) -> None:  # noqa: B027
        """
        If there's no request to process, do this instead.
        """
        pass


class BaseController[I, O]:
    """Base class for worker controllers"""

    _worker: BaseWorker[I, O]
    _process: Optional[Process]
    _control: WorkerControl
    _pending_responses: dict[str, Future[O]]
    _async_queue: Optional[AsyncQueue[Response[O]]]
    _response_task: Optional[asyncio.Task]

    def __init__(self, worker: BaseWorker[I, O]):
        self._worker = worker
        self._process = None
        self._control = WorkerControl(
            input_queue=Queue(),
            output_queue=Queue(),
            state_condition=Condition(),
            work_available=Condition(),
            stop_event=Event(),
        )
        # Mapping of correlation IDs to Futures
        self._pending_responses = {}
        # Queue for distributing responses to async handlers
        self._async_queue = None
        self._response_task = None

    def start(self) -> None:
        """Start the worker process"""
        self._worker.init_control(self._control)

        self._process = Process(target=self._worker.run_worker)
        self._process.start()

        # Initialize async components
        self._async_queue = AsyncQueue()
        self._response_task = asyncio.create_task(self._handle_responses())

    async def _handle_responses(self) -> None:
        """Background task to handle responses from the worker process"""
        while True:
            try:
                # Check for responses with a timeout to allow clean shutdown
                response = await asyncio.get_event_loop().run_in_executor(
                    None, self._control.output_queue.get, True, 1.0
                )

                if isinstance(response, Exception):
                    # Handle worker error
                    for future in self._pending_responses.values():
                        if not future.done():
                            future.set_exception(response)
                    self._pending_responses.clear()
                    continue

                # Find and complete the corresponding Future
                future = self._pending_responses.pop(response.id, None)
                if future and not future.done():
                    future.set_result(response.payload)

            except Empty:
                # Check if we should exit
                if self._control.stop_event.is_set():
                    break
                continue
            except Exception as e:
                logging.exception("Error handling responses")
                # Propagate error to all pending futures
                for future in self._pending_responses.values():
                    if not future.done():
                        future.set_exception(e)
                self._pending_responses.clear()
                break

    def stop(self) -> None:
        """Stop the worker process"""
        if self._process and self._process.is_alive():
            self._control.stop_event.set()
            # Wake up the worker if it's waiting
            with self._control.work_available:
                self._control.work_available.notify()
            self._process.join(timeout=5.0)
            if self._process.is_alive():
                self._process.terminate()

            # Clean up async resources
            if self._response_task:
                self._response_task.cancel()

    def send_message(self, message: I) -> None:
        """Send a message to the worker"""
        msg = Message(id=str(uuid.uuid4()), payload=message)
        self._control.input_queue.put(msg)
        # Signal that work is available
        with self._control.work_available:
            self._control.work_available.notify()

    async def request(self, message: I) -> O:
        """Send a message and wait for its response asynchronously"""
        msg_id = str(uuid.uuid4())
        future: Future[O] = asyncio.Future()

        # Register the future before sending the message
        self._pending_responses[msg_id] = future

        try:
            # Send the message
            msg = Message(id=msg_id, payload=message)
            self._control.input_queue.put(msg)
            # Signal that work is available
            with self._control.work_available:
                self._control.work_available.notify()

            # Wait for the response
            return await future

        except Exception:
            # Clean up on error
            self._pending_responses.pop(msg_id, None)
            raise

    def get_result(self, timeout: Optional[float] = None) -> O:
        """Get next result from the worker (for non-async usage)"""
        response: Response[O] = self._control.output_queue.get(timeout=timeout)
        return response.payload

    def wait_for_state(self, state: WorkerState, timeout: Optional[float] = None) -> bool:
        """Wait for worker to reach specified state"""
        assert self._control is not None
        assert self._worker is not None
        with self._control.state_condition:
            if self._worker.state == state:
                return True
            return self._control.state_condition.wait_for(
                lambda: self._worker.state == state, timeout=timeout
            )


class NumberSquarer(BaseWorker[int, int]):
    def process_message(self, message: int) -> int:
        return message * message


if __name__ == "__main__":

    async def main():
        worker = NumberSquarer()
        controller = BaseController(worker)
        controller.start()

        try:
            # Send a request and await its result
            result = await controller.request(5)
            print(f"5 squared is {result}")

            # Can send multiple requests concurrently
            results = await asyncio.gather(
                controller.request(2), controller.request(3), controller.request(4)
            )
            print(f"Results: {results}")

        finally:
            controller.stop()

    asyncio.run(main())
