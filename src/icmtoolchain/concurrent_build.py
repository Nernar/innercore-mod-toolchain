from .context import GLOBALS
import asyncio
import contextlib
import io
import sys
from dataclasses import dataclass
from itertools import cycle
from os.path import basename
from queue import Empty, Queue
from typing import Any, Dict, List, Optional, Tuple, cast

from prompt_toolkit import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.bindings.focus import (focus_next,
                                                       focus_previous)
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import HSplit, Layout, ScrollablePane, ScrollOffsets
from prompt_toolkit.widgets import TextArea

from .language import MakeDataConfig
from .project_graph import ConcurrentScheduler, ProjectEdge, ProjectGraph
from .shell import (Interactable, Progress, abort, attention,
                    get_toolchain_style, pretty_error, pretty_exception,
                    pretty_print)
from .task import TASKS
from .utils import RuntimeCodeError


@dataclass
class TaskEvent:
	type: str
	project: str
	task_name: str
	text: str

@dataclass
class BuildStatus:
	has_failure: bool = False
	failure_code: int = 1

def worker_execute_project_tasks(node: ProjectEdge, task_names: List[str], queue: Optional[Queue] = None) -> Tuple[int, List[Tuple[str, str]]]:
	if not isinstance(node.project, MakeDataConfig):
		raise RuntimeError(f"Project {node} is not populated!")

	pass
	GLOBALS.shutdown_project()
	GLOBALS.make_config = node.project
	project_spec = str(node)

	overall_result = 0
	all_task_logs = []

	for task_name in task_names:
		buffer = io.StringIO()
		with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
			if task_name not in TASKS:
				attention(f"No such task: {task_name}.")
				overall_result = 1
				all_task_logs.append((task_name, buffer.getvalue()))
				break

			callable_task = TASKS[task_name]

			if queue:
				queue.put(TaskEvent(
					type="start",
					project=project_spec,
					task_name=callable_task.name,
					text=callable_task.description or callable_task.name
				))
				callable_task.on_status_changed = lambda status, pn=project_spec, tn=callable_task.name: queue.put(TaskEvent(
					type="status",
					project=pn,
					task_name=tn,
					text=status
				))

			try:
				result = callable_task.callable()
				if result != 0:
					overall_result = cast(int, result)
					all_task_logs.append((task_name, buffer.getvalue()))
					break
			except BaseException as err:
				if isinstance(err, SystemExit):
					overall_result = int(err.code) if err.code is not None else 0
					all_task_logs.append((task_name, buffer.getvalue()))
					break
				if isinstance(err, RuntimeCodeError):
					pretty_error(f"Task {callable_task.name} failed with error code #{err.code}: {err}")
				else:
					pretty_error(f"Task {callable_task.name} failed with unexpected error!")
					pretty_exception(err)
				overall_result = 255
				all_task_logs.append((task_name, buffer.getvalue()))
				break
			finally:
				if queue:
					callable_task.on_status_changed = None
		all_task_logs.append((task_name, buffer.getvalue()))

	return overall_result, all_task_logs


class WorkerStatePane:
	def __init__(self, index: int):
		self.index = index
		self.project = None
		self.message = "Idle"
		self.frames = cycle(["▀", "▄"])
		self.content = TextArea(dont_extend_height=True, read_only=True)
		self.description = Interactable(text="")
		self.is_active = False

	async def run(self):
		while True:
			if self.project:
				self.content.text = f"{next(self.frames)} [{self.project}] {self.message}"
				self.description.text = "   " * 2 + f"Running task..."
			else:
				self.content.text = f"  [Worker {self.index}] Waiting for tasks..."
				self.description.text = ""
			await asyncio.sleep(0.15)
			if not self.is_active and not self.project:
				break

	def set_active(self, project: str, message: str):
		self.project = project
		self.message = message

	def set_idle(self):
		self.project = None

	def update_message(self, message: str):
		if self.project:
			self.message = message

class ConcurrentBuilderApp:
	def __init__(self, total_tasks: int, max_workers: int):
		self.worker_panes = [WorkerStatePane(i) for i in range(1, max_workers + 1)]
		self.total_tasks = total_tasks
		self.overall_progress = Progress()

		contents = [self.overall_progress]
		for pane in self.worker_panes:
			contents += [pane.content, pane.description]

		root_container = ScrollablePane(
			HSplit(contents),
			scroll_offsets=ScrollOffsets(3, 3),
			display_arrows=False,
		)

		self.layout = Layout(root_container)
		kb = KeyBindings()

		@kb.add("c-c")
		@kb.add("<sigint>")
		def _(event):
			event.app.exit()
			raise KeyboardInterrupt()

		kb.add(Keys.Down)(focus_next)
		kb.add(Keys.Up)(focus_previous)

		self.app = Application(
			layout=self.layout,
			style=get_toolchain_style(),
			include_default_pygments_style=False,
			key_bindings=kb,
			full_screen=False,
			mouse_support=True,
			erase_when_done=True
		)
		self.update_progress(0)

	def assign_worker(self, project: str, message: str) -> Optional[WorkerStatePane]:
		pane = next((p for p in self.worker_panes if p.project is None), None)
		if pane:
			pane.set_active(project, message)
		return pane

	def update_worker_status(self, project: str, message: str):
		for pane in self.worker_panes:
			if pane.project == project:
				pane.update_message(message)

	def update_progress(self, completed_count: int):
		self.overall_progress.update(completed_count / self.total_tasks, f"Building {completed_count}/{self.total_tasks} projects...")

	def stop_workers(self):
		for pane in self.worker_panes:
			pane.is_active = False
			pane.set_idle()

	async def run_async(self):
		for pane in self.worker_panes:
			pane.is_active = True
			self.app.create_background_task(pane.run())
		await self.app.run_async()

	def exit(self):
		self.app.exit()


async def build_executor_loop(app: ConcurrentBuilderApp, scheduler: ConcurrentScheduler, task_names: List[str], max_workers: int, queue: Queue, all_logs: list, status_obj: BuildStatus):
	from concurrent.futures import ProcessPoolExecutor
	loop = asyncio.get_event_loop()
	with ProcessPoolExecutor(max_workers=max_workers) as executor:
		pending_futures: Dict[Any, Tuple[ProjectEdge, Optional[WorkerStatePane]]] = {}

		while scheduler.has_unfinished_tasks():
			ready_nodes = scheduler.fetch_ready_nodes()
			for node in ready_nodes:
				scheduler.acquire_node(node)

				project_name = str(node)
				pane = app.assign_worker(project_name, "Initializing...")

				future = loop.run_in_executor(
					executor,
					worker_execute_project_tasks,
					node,
					task_names,
					queue
				)
				pending_futures[future] = (node, pane)

			if not pending_futures:
				await asyncio.sleep(0.1)
				continue

			done, _ = await asyncio.wait(pending_futures.keys(), return_when=asyncio.FIRST_COMPLETED, timeout=0.1)

			while not queue.empty():
				try:
					msg = queue.get_nowait()
					if isinstance(msg, TaskEvent):
						if msg.type in ("start", "status"):
							app.update_worker_status(msg.project, msg.text)
				except Empty:
					break

			for future in done:
				node, pane = pending_futures.pop(future)
				if pane:
					pane.set_idle()
				node_spec = str(node)
				try:
					result, logs = future.result()
					all_logs.append((node_spec, logs))
					if result != 0:
						status_obj.has_failure = True
						status_obj.failure_code = result
						all_logs.append((node_spec, [("Error", f"Concurrent tasks failed for {node_spec} with code {result}.")]))
				except Exception as err:
					status_obj.has_failure = True
					all_logs.append((node_spec, [("Error", f"Concurrent executor failed: {err}")]))
					
				scheduler.complete_node(node)
				app.update_progress(len(scheduler.completed))

	app.stop_workers()
	app.exit()

async def run_concurrent_build(graph: 'ProjectGraph', task_names: List[str]):
	import multiprocessing
	if multiprocessing.get_start_method(allow_none=True) != "spawn":
		preferred_method = "spawn"
		if "forkserver" in multiprocessing.get_all_start_methods():
			preferred_method = "forkserver"
		try:
			multiprocessing.set_start_method(preferred_method, force=True)
		except RuntimeError:
			pass

	if sys.version_info < (3, 13):
		from os import cpu_count as _cpu_count
		cpu_count = _cpu_count()
	else:
		from os import process_cpu_count
		cpu_count = process_cpu_count()

	max_workers = max(1, cpu_count // 2 if cpu_count else 1)

	scheduler = ConcurrentScheduler(graph)
	manager = multiprocessing.Manager()
	queue = manager.Queue()

	app = ConcurrentBuilderApp(len(scheduler.pending), max_workers)
	all_logs = []
	build_status = BuildStatus()

	executor_task = asyncio.create_task(build_executor_loop(app, scheduler, task_names, max_workers, queue, all_logs, build_status))

	try:
		await app.run_async()
	except KeyboardInterrupt:
		build_status.has_failure = True
		all_logs.append(("<runner>", [("Error", "Tasks stopped gracefully.")]))
	finally:
		for project_dir, task_logs in all_logs:
			has_output = any(logs.strip() for _, logs in task_logs)
			if has_output:
				pretty_print(f"--- Logs for {basename(project_dir)} ---", style="class:print.info")
				for task_name, logs in task_logs:
					if logs.strip():
						pretty_print(f"[{task_name}]:", style="class:print.debug")
						print(logs, end="")
				pretty_print("-" * (18 + len(basename(project_dir))), style="class:print.info")
		if build_status.has_failure:
			abort("Concurrent build failed.", code=build_status.failure_code)
