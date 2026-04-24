from typing import Any, Callable, Dict, Final, List, Optional
from os.path import join

from .output_directory import get_temporary_directory, lock_file, unlock_file
from .logger import print

class Task:
	name: Final[str]
	description: str = ""
	_status: Optional[str] = None
	callable: Callable
	locks: Optional[List[str]] = None
	on_status_changed: Optional[Callable[[str], None]] = None

	@property
	def status(self) -> str:
		if not self._status:
			return f"Running task {self.name}..."
		return self._status

	@status.setter
	def status(self, value: str) -> None:
		self._status = value
		if self.on_status_changed:
			self.on_status_changed(value)

	def __init__(
		self,
		name: str,
		description: Optional[str] = None,
		status: Optional[str] = None,
		locks: Optional[List[str]] = None,
		*,
		yield_message: Optional[str] = "Task is already running by another process, wait for unlocking.",
		continue_message: Optional[str] = "Lock is released, resuming task..."
	) -> None:
		try:
			if assure_task(name) == self:
				return
		except ValueError:
			pass
		else:
			raise ValueError(f"Task {name!r} is already exists.")
		self.name = name
		if description:
			self.description = description
		if status:
			self.status = status
		if locks:
			self.locks = locks
		self.yield_message = yield_message
		self.continue_message = continue_message
		self.locks_directory = join(get_temporary_directory(), "locks")

	def execute(self, silent: bool = True, *args, **kwargs) -> Any:
		if not self.callable:
			raise ValueError(f"Task {self.name!r} decorator is not assigned to function.")
		self.lock(silent)
		if not silent:
			print(f"> Executing task: {self.name}", style="class:task.execute")
		result = self.callable.__call__(*args, **kwargs)
		self.unlock()
		return result

	def __call__(self, *args, **kwargs):
		return self.execute(False, *args, **kwargs)

	def lock_of(self, name: str) -> str:
		return join(self.locks_directory, f"{name}.lock")

	def lock(self, silent: bool = False) -> None:
		yield_message = self.yield_message if not silent else None
		continue_message = self.continue_message if not silent else None
		lock_file(self.lock_of(self.name), yield_message=yield_message, continue_message=continue_message)
		if not self.locks:
			return
		locks = iter(self.locks)
		while True:
			try:
				lock_file(self.lock_of(next(locks)), yield_message=yield_message, continue_message=continue_message)
			except StopIteration:
				break

	def unlock(self) -> None:
		unlock_file(self.lock_of(self.name))
		if not self.locks:
			return
		locks = iter(self.locks)
		while True:
			try:
				unlock_file(self.lock_of(next(locks)))
			except StopIteration:
				break

TASKS: Dict[str, Task] = dict()


def assure_task(name: str) -> Task:
	tasks = iter(TASKS)
	while True:
		try:
			task = next(tasks)
		except StopIteration:
			raise ValueError(f"Task {name!r} is not registered.")
		else:
			if task == name:
				return TASKS[task]

def execute_task(name: str, silent: bool = True, *args, **kwargs) -> Any:
	return assure_task(name) \
		.execute(silent=silent, *args, **kwargs)

def task(name: str, description: Optional[str] = None, status: Optional[str] = None, locks: Optional[List[str]] = None) -> Callable[[Callable], Callable]:
	task = Task(name, description, status, locks)

	def decorator(callable: Callable) -> Callable:
		task.callable = callable
		TASKS[name] = task
		return task

	return decorator
