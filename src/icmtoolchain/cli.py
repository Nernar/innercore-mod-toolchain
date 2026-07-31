import asyncio
import sys
from itertools import tee
from os import listdir
from os.path import dirname, isdir, isfile, join
from time import time
from typing import (TYPE_CHECKING, Iterator, MutableSequence, MutableSet,
                    NoReturn, Optional)

from .config import FileConfig
from .context import GLOBALS
from .errors import ToolchainError
from .logger import attention, error, failure, print, success, trace
from .project_graph import ProjectEdge, ProjectGraph
from .shell import UNICODE_BALLOT_X, pretty_ansi_layers
from .utils import RuntimeCodeError

if TYPE_CHECKING:
	from .task import BaseScheduledTask


def show_help(requires_art: bool = False):
	if requires_art:
		show_ansi_toolchain()
		print()
	print("Usage: icmtoolchain [options] ... <task1> [arguments1] ...")
	print(" " * 2 + "--help: Display this message.")
	print(" " * 2 + "--list: See available tasks.")
	print("Perform commands marked with a special decorator @task.")
	print("Example: icmtoolchain pushEverything launchApplication")

def show_available_tasks():
	from . import builtin_tasks
	from .task import TASKS
	print("All available tasks:")
	for name, task in TASKS.items():
		print(" " * 2 + name, end="")
		if task.description:
			print(": " + task.description, end="")
		print()

def show_ansi_toolchain():
	pretty_ansi_layers(
		[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 124, 0, 0, 0, 0, 0, 0, 0, 0, 0],
		[0, 0, 0, 0, 0, 0, 0, 0, 196, 160, 196, 196, 196, 196, 0, 0, 0, 0, 0, 0, 196, 160, 0, 0, 0, 0, 0, 0, 0],
		[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 196, 196, 196, 196, 160, 0, 0, 0, 0, 196, 0, 0, 0, 0, 0, 0, 0],
		[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 196, 196, 196, 196, 0, 0, 0, 196, 196, 0, 0, 0, 0, 0, 0],
		[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 160, 196, 196, 160, 196, 160, 160, 0, 160, 0, 0, 196, 196, 0, 0, 0, 0, 0],
		[0, 0, 0, 0, 0, 160, 196, 196, 196, 196, 0, 0, 160, 196, 196, 196, 0, 220, 0, 160, 196, 0, 196, 196, 0, 0, 0, 0, 0],
		[0, 0, 0, 160, 196, 196, 196, 196, 196, 0, 0, 0, 226, 220, 196, 196, 196, 214, 220, 0, 196, 160, 196, 196, 196, 0, 0, 0, 0],
		[0, 0, 196, 196, 196, 160, 0, 196, 196, 196, 202, 208, 220, 226, 226, 202, 202, 196, 226, 226, 196, 196, 196, 196, 196, 0, 0, 0, 160],
		[0, 196, 196, 0, 0, 160, 196, 196, 196, 196, 196, 208, 214, 214, 214, 220, 2, 214, 220, 226, 196, 196, 0, 160, 196, 0, 0, 0, 196],
		[160, 160, 0, 0, 160, 196, 160, 172, 202, 214, 214, 2, 2, 7, 7, 7, 2, 7, 2, 214, 196, 196, 0, 0, 196, 0, 0, 0, 196],
		[0, 0, 0, 0, 0, 0, 0, 0, 226, 226, 2, 7, 7, 7, 7, 7, 7, 7, 7, 2, 214, 196, 0, 0, 0, 160, 0, 160, 196],
		[0, 0, 0, 160, 196, 0, 0, 166, 208, 226, 2, 7, 7, 7, 7, 7, 7, 7, 7, 2, 220, 208, 226, 0, 196, 196, 0, 196, 196],
		[0, 0, 0, 196, 196, 0, 196, 196, 214, 226, 7, 7, " I", "nn", "er", " C", "or", "e ", 7, 7, 214, 226, 226, 124, 196, 196, 0, 196, 160],
		[0, 0, 196, 196, 196, 160, 196, 196, 214, 2, 7, 7, " M", "od", 7, 7, 7, 7, 7, 7, 2, 226, 208, 196, 196, 0, 196, 196, 0],
		[0, 0, 196, 196, 0, 196, 196, 214, 220, 2, 7, 7, " T", "oo", "lc", "ha", "in", 7, 7, 7, 2, 214, 196, 196, 196, 196, 196, 196, 0],
		[0, 160, 196, 0, 196, 196, 124, 226, 220, 2, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 2, 214, 196, 202, 0, 196, 196, 0, 0]
	)

def show_unresolved_dependencies(dependencies: MutableSet[ProjectEdge]) -> None:
	if not any(dependencies):
		return
	attention(f"We were unable to resolve following dependencies: {', '.join(str(dependency) for dependency in dependencies)}")

def resolve_circular_references(graph: ProjectGraph) -> bool:
	circular_reference = graph.find_circular_reference()
	if not circular_reference:
		return False
	repr_circular_references = []
	while circular_reference:
		repr_circular_references.append(f"{circular_reference[0]} -> {circular_reference[1]}")
		graph.undepend_on(circular_reference[0], circular_reference[1], keep_unused=True)
		circular_reference = graph.find_circular_reference()
	attention(f"Circular dependencies detected, make sure your projects are configured correctly: {', '.join(repr_circular_references)}.")
	unused_edges = graph.remove_unused_edges()
	if any(unused_edges):
		repr_unused_edges = [f"{edge}" for edge in unused_edges]
		failure(f"Following dependencies have been removed as there is no further connection in them to other projects: {', '.join(repr_unused_edges)}!")
		raise RuntimeError("Cannot build a project with unresolved dependencies!")
	return True

def execute_task(scheduled_task: 'BaseScheduledTask') -> None:
	try:
		result = scheduled_task()
		if result not in (0, None):
			raise ToolchainError(f"Task {scheduled_task.name} failed with result {result}.", code=result)
	except ToolchainError:
		raise
	except BaseException as err:
		if isinstance(err, SystemExit):
			raise err
		if isinstance(err, RuntimeCodeError):
			raise ToolchainError(f"Task {scheduled_task.name} failed with error code #{err.code}: {err}", code=err.code)
		raise ToolchainError(f"Task {scheduled_task.name} failed with unexpected error!", cause=err)

def build_project_graph() -> ProjectGraph:
	graph = ProjectGraph(GLOBALS.MAKE_CONFIG)
	graph.collect_dependencies(GLOBALS.MAKE_CONFIG)
	unresolved_artifacts = graph.resolve_dependencies()
	show_unresolved_dependencies(unresolved_artifacts)
	resolve_circular_references(graph)
	return graph

def run_sequential_build(graph: ProjectGraph, targets: Iterator['BaseScheduledTask']) -> None:
	from .language import MakeDataConfig
	dependencies = graph.traverse_dependencies()
	for scheduled_task in targets:
		scheduled_task.prepare(dependencies)
	for edge in dependencies:
		GLOBALS.switch_to_project(edge)
		targets, tasks = tee(targets)
		for scheduled_task in tasks:
			execute_task(scheduled_task)

def run_single_build(targets: Iterator['BaseScheduledTask']) -> None:
	for scheduled_task in targets:
		scheduled_task.prepare()
		execute_task(scheduled_task)

def run(argv: Optional[MutableSequence[str]] = None):
	if not argv or len(argv) == 0:
		argv = sys.argv
	if "--help" in argv or len(argv) <= 1:
		show_help(requires_art=len(argv) <= 1)
		exit(0)
	if "--list" in argv:
		show_available_tasks()
		exit(0)
	if "--concurrent-test" in argv:
		asyncio.run(run_concurrent_test(), debug=True)
		exit(0)
	if "--example" in argv:
		example_offset = argv.index("--example")
		run_example_test(argv[example_offset + 1] if len(argv) > example_offset + 1 else "complex")
		exit(0)

	startup_millis = time()
	argv = argv[1:]

	is_concurrent = False
	if "--concurrent" in argv:
		is_concurrent = True
		argv.remove("--concurrent")

	from . import builtin_tasks
	from .parser import apply_environment_properties, parse_arguments
	from .task import TASKS

	try:
		targets = parse_arguments(argv, TASKS, lambda name, target, callables: attention(f"No such task: {name}."))
	except (TypeError, ValueError) as err:
		error(" ".join(argv))
		force_exit(cause=err)

	apply_environment_properties()

	targets, has_anything = tee(targets)
	try:
		next(has_anything)
	except StopIteration:
		attention("No tasks to execute.")
		exit(0)

	try:
		if GLOBALS.is_project_available():
			graph = build_project_graph()

			if is_concurrent:
				from .concurrent_build import run_concurrent_build
				asyncio.run(run_concurrent_build(graph, targets))
			else:
				run_sequential_build(graph, targets)
		else:
			run_single_build(targets)
	except ToolchainError as err:
		force_exit(err.message, code=err.code, cause=err.cause)

	startup_millis = time() - startup_millis
	success(f"Tasks successfully completed in {startup_millis:.2f}s!")

def perform_concurrent_tasks(slave: FileConfig):
	return f"{slave.path}: {slave.as_json()}"

async def run_concurrent_test():
	import multiprocessing
	from concurrent.futures import ProcessPoolExecutor

	if multiprocessing.get_start_method() == "fork":
		preferred_method = "spawn"
		if "forkserver" in multiprocessing.get_all_start_methods():
			preferred_method = "forkserver"
		multiprocessing.set_start_method(preferred_method, True)
	secs = time()
	if sys.version_info < (3, 13):
		from os import cpu_count as _cpu_count
		cpu_count = _cpu_count()
	else:
		from os import process_cpu_count
		cpu_count = process_cpu_count()
	max_workers = cpu_count // 2 if cpu_count else 1
	index = 0

	def fetch_available_projects(index):
		if index == 0:
			for _ in range(max_workers):
				yield GLOBALS.PREFERRED_CONFIG
			return
		elif index >= 50:
			return

		yield GLOBALS.PREFERRED_CONFIG

	with ProcessPoolExecutor(max_workers=max_workers) as executor:
		loop = asyncio.get_event_loop()
		scheduled_queue = asyncio.Queue()

		warmup_projects = fetch_available_projects(index)
		for project in warmup_projects:
			await scheduled_queue.put(project)
			index += 1

		semaphore = asyncio.Semaphore(max_workers)

		async def process_project(config: FileConfig):
			nonlocal index
			async with semaphore:
				result = await loop.run_in_executor(
					executor,
					perform_concurrent_tasks,
					config
				)
				print(result)

				available_projects = fetch_available_projects(index)
				for project in available_projects:
					await scheduled_queue.put(project)
					index += 1

				return result

		tasks = set()

		async def worker():
			while tasks or not scheduled_queue.empty():
				try:
					project = await asyncio.wait_for(scheduled_queue.get(), timeout=1.0)
				except asyncio.TimeoutError:
					if not tasks and scheduled_queue.empty():
						return
					continue

				task = asyncio.create_task(process_project(project))
				tasks.add(task)
				task.add_done_callback(lambda task: tasks.discard(task))

		worker_tasks = [asyncio.create_task(worker()) for _ in range(max_workers)]

		await asyncio.gather(*worker_tasks)
		if tasks:
			await asyncio.gather(*tasks)

	print(f"Completed {index} tasks in {time() - secs:.2f}ms on {max_workers} CPUs.")

def run_example_test(name: str):
	examples_directory = join(dirname(__file__), "..", "..", "examples")
	if not isdir(examples_directory):
		raise RuntimeError("Examples directory is not available.")
	example_executable = join(examples_directory, name, "__main__.py")
	if not isfile(example_executable):
		raise RuntimeError(f"No such example {name!r}. It should be one of: {', '.join(listdir(examples_directory))}.")

	from importlib.util import module_from_spec, spec_from_file_location
	example_name = f"{__name__[:__name__.rindex('.')]}.examples.{name}"
	example_spec = spec_from_file_location(example_name, example_executable)
	if not example_spec:
		raise RuntimeError(f"Cannot obtain example {name!r} spec.")
	example_module = module_from_spec(example_spec)
	sys.modules[example_name] = example_module
	if not example_spec.loader:
		raise RuntimeError(f"Cannot obtain example {name!r} module loader.")
	example_spec.loader.exec_module(example_module)

def force_exit(*values: object, sep: Optional[str] = " ", code: int = 255, cause: Optional[BaseException] = None) -> NoReturn:
	if cause:
		trace(cause, is_error=True)
	if len(values) != 0:
		print(UNICODE_BALLOT_X, style="class:print.failure", end=" ")
		print(*values, sep=sep, style="class:print.abort-message")
	elif not cause:
		print("Abort.")
	from .task import TASKS
	for name, task in TASKS.items():
		try:
			task.unlock()
		except IOError:
			pass
	exit(code)
