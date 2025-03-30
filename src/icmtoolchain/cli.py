import sys
from typing import Optional

def show_help():
	print("Usage: icmtoolchain [options] ... <task1> [arguments1] ...")
	print(" " * 2 + "--help: Display this message.")
	print(" " * 2 + "--list: See available tasks.")
	print("Perform commands marked with a special decorator @task.")
	print("Example: icmtoolchain selectProject --path mod1 pushEverything selectProject --path mod2 pushEverything launchApplication")

def show_available_tasks():
	from .task import TASKS
	print("All available tasks:")
	for name, task in TASKS.items():
		print(" " * 2 + name, end="")
		if task.description:
			print(": " + task.description, end="")
		print()

def run(argv: Optional[list[str]] = None):
	if not argv or len(argv) == 0:
		argv = sys.argv
	if "--help" in argv or len(argv) <= 1:
		show_help()
		exit(0)
	if "--list" in argv:
		show_available_tasks()
		exit(0)

	from time import time
	startup_millis = time()
	argv = argv[1:]

	from .parser import apply_environment_properties, parse_arguments
	from .shell import abort, debug, error, warn
	from .task import TASKS

	try:
		targets = parse_arguments(argv, TASKS, lambda name, target, callables: warn(f"* No such task: {name}."))
	except (TypeError, ValueError) as err:
		error(" ".join(argv))
		abort(cause=err)

	apply_environment_properties()

	anything_performed = False
	tasks = iter(targets)
	while True:
		try:
			callable = next(tasks)
		except StopIteration:
			break
		else:
			try:
				result = callable.callable()
				if result != 0:
					abort(f"* Task {callable.name} failed with result {result}.", code=result)
			except BaseException as err:
				if isinstance(err, SystemExit):
					raise err
				from .utils import RuntimeCodeError
				if isinstance(err, RuntimeCodeError):
					abort(f"* Task {callable.name} failed with error code #{err.code}: {err}")
				abort(f"* Task {callable.name} failed with unexpected error!", cause=err)
			anything_performed = True

	if not anything_performed:
		debug("* No tasks to execute.")
		exit(0)

	from .task import unlock_all_tasks
	unlock_all_tasks()

	startup_millis = time() - startup_millis
	debug(f"* Tasks successfully completed in {startup_millis:.2f}s!")
