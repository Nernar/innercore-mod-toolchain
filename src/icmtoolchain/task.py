from os.path import basename, dirname, isdir, isfile, join, relpath
from typing import Any, Callable, Dict, Final, List, Optional

from . import GLOBALS, PROPERTIES
from .output_directory import get_temporary_directory, lock_file, unlock_file
from .shell import (abort, confirm_prompt, error, pretty_print,
                    pretty_print_success, warn)
from .utils import DEVNULL, remove_tree


class Task:
	name: Final[str]
	description: str = ""
	callable: Callable
	locks: Optional[List[str]] = None

	def __init__(
		self,
		name: str,
		description: Optional[str] = None,
		locks: Optional[List[str]] = None,
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
			pretty_print(f"> Executing task: {self.name}", style="class:task.execute")
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

def task(name: str, description: Optional[str] = None, locks: Optional[List[str]] = None) -> Callable[[Callable], Callable]:
	task = Task(name, description, locks)

	def decorator(callable: Callable) -> Callable:
		task.callable = callable
		TASKS[name] = task
		return task

	return decorator

### JAVASCRIPT, TYPESCRIPT, JAVA, C++

@task(
	"compileNative",
	locks=["native", "cleanup", "push"],
	description="Compiles native folders using NDK and links objects."
)
def task_compile_native() -> int:
	if not GLOBALS.MAKE_CONFIG.supports_native:
		return 0
	abis = None
	if not PROPERTIES.get_value("release"):
		abi = GLOBALS.MAKE_CONFIG.get_value("native.debugAbi")
		if not abi:
			abi = GLOBALS.MAKE_CONFIG.get_value("debugAbi")
		if abi:
			# TODO: warn("* Property `debugAbi` has been deprecated in favor of configurations, determine your own ABIs via 'debug' rule.")
			abis = [abi]
	if not abis:
		abis = GLOBALS.MAKE_CONFIG.obtain_list("native.abis")
		if len(abis) == 0:
			abis = GLOBALS.MAKE_CONFIG.obtain_list("abis")
	if len(abis) == 0:
		abort(f"No `abis` value in 'toolchain.json' config, nothing will happened.")
	from .native_build import compile_native, copy_shared_objects
	result = compile_native(abis)
	if result == 0 and GLOBALS.MAKE_CONFIG.supports_shared_objects:
		result = copy_shared_objects(abis)
	return result

@task(
	"compileJava",
	locks=["java", "cleanup", "push"],
	description="Compiles java folders using Gradle, Javac or ECJ."
)
def task_compile_java(tool: Optional[str] = None) -> int:
	if not GLOBALS.MAKE_CONFIG.supports_java:
		return 0
	from .java_build import compile_java
	if not tool:
		tool = GLOBALS.MAKE_CONFIG.get_value("java.compiler", "gradle")
	if not tool:
		return 1
	if not tool == "gradle" and GLOBALS.MAKE_CONFIG.get_value("java.configurable", False):
		warn("* Project uses configurable Gradle, different tools cannot be applied.")
		tool = "gradle"
	return compile_java(tool)

@task(
	"buildScripts",
	locks=["script", "cleanup", "push"],
	description="Recompiles scripts using simple file concatenation or tsc."
)
def task_build_scripts() -> int:
	if not GLOBALS.MAKE_CONFIG.supports_scripts:
		return 0
	from .script_build import build_all_scripts
	return build_all_scripts()

@task(
	"watchScripts",
	locks=["script", "cleanup", "push"],
	description="Recompiles changed scripts instantly using tsc, interruption will end watching."
)
def task_watch_scripts() -> int:
	if not GLOBALS.MAKE_CONFIG.supports_scripts:
		error("* You cannot have scripts to watch because your project does not support them.")
		return 1
	from .script_build import build_all_scripts
	return build_all_scripts(watch=True)

@task(
	"updateIncludes",
	description="Overrides the contents of 'tsconfig.json' based on script files."
)
def task_update_includes() -> int:
	if not GLOBALS.MAKE_CONFIG.supports_scripts:
		return 0
	from .script_build import compute_and_capture_changed_scripts
	compute_and_capture_changed_scripts()
	GLOBALS.TSC_COMPOSITE.flush()
	return 0

### RESOURCES & PACKAGE

@task(
	"buildResources",
	locks=["resource", "cleanup", "push"],
	description="Copies predefined resources consisting of textures, in-game packs, etc."
)
def task_resources() -> int:
	from .resources import (build_additional_resources, build_pack_graphics,
	                        build_resources)
	if GLOBALS.MAKE_CONFIG.supports_resources:
		overall_result = build_resources()
	if overall_result == 0 and GLOBALS.MAKE_CONFIG.supports_pack_graphics:
		overall_result = build_pack_graphics()
	if overall_result == 0:
		overall_result = build_additional_resources()
	if overall_result == 0:
		GLOBALS.LINKED_RESOURCE_STORAGE.save_contents()
	return overall_result

@task(
	"buildInfo",
	locks=["cleanup", "push"],
	description="Writes the description file 'mod.info' to output folder for display in mod browser."
)
def task_build_info() -> int:
	project_data = GLOBALS.MAKE_CONFIG.obtain_project_data()
	if project_data is None:
		warn("* Nothing to write in project configurations, project data does not exist.")
		return 0
	return project_data.flush_to_output(GLOBALS.MOD_STRUCTURE.directory)

@task(
	"clearOutput",
	locks=["assemble", "push", "native", "java", "resource", "script"],
	description="Optionally deletes the output folder; has no effect by default."
)
def task_clear_output(force: bool = False) -> int:
	if GLOBALS.MAKE_CONFIG.get_value("development.clearOutput", False) or force:
		remove_tree(GLOBALS.MOD_STRUCTURE.directory)
	if PROPERTIES.get_value("release"):
		from .package import pretty_cleanup_directory
		pretty_cleanup_directory(GLOBALS.MAKE_CONFIG.get_build_path())
	return 0

@task(
	"buildPackage",
	locks=["push", "assemble", "native", "java", "resource", "script"],
	description="Assembles project's output folder into an archive, specifically for publishing in a mod browser."
)
def task_build_package() -> int:
	from .resources import build_package
	return build_package()

### CONNECTION

@task(
	"pushEverything",
	locks=["push"],
	description="Sends assembled output folder to a connected device."
)
def task_push_everything() -> int:
	from .device import push_everything
	return push_everything()

@task(
	"launchApplication",
	description="Starts launcher with predefined autostart setting on a connected device using ADB."
)
def task_monkey_launcher() -> int:
	from subprocess import run
	run(GLOBALS.ADB_COMMAND + [
		"shell", "input",
		"keyevent", "KEYCODE_WAKEUP"
	], stdout=DEVNULL, stderr=DEVNULL)
	try:
		process = run(GLOBALS.ADB_COMMAND + [
			"shell", "monkey",
			"-p", "com.zheka.horizon",
			"-c", "android.intent.category.LAUNCHER", "1"
		], check=True, capture_output=True, text=True)
		successful = False
		for line in process.stdout.splitlines():
			if line[:15] == "Events injected":
				successful = True
				break
		if not successful:
			raise RuntimeError()
		run(GLOBALS.ADB_COMMAND + [
			"shell", "touch",
			"/storage/emulated/0/games/horizon/.flag_auto_launch"
		], stdout=DEVNULL, stderr=DEVNULL)
		run(GLOBALS.ADB_COMMAND + [
			"shell", "touch",
			"/storage/emulated/0/Android/data/com.zheka.horizon/files/horizon/.flag_auto_launch"
		], stdout=DEVNULL, stderr=DEVNULL)
	except BaseException:
		try:
			process = run(GLOBALS.ADB_COMMAND + [
				"shell", "monkey",
				"-p", "com.zhekasmirnov.innercore",
				"-c", "android.intent.category.LAUNCHER", "1"
			], check=True, capture_output=True, text=True)
			successful = False
			for line in process.stdout.splitlines():
				if line[:15] == "Events injected":
					successful = True
					break
			if not successful:
				raise RuntimeError()
		except BaseException:
			warn("* Horizon is not installed, nothing to launch.")
	return 0

@task(
	"stopApplication",
	description="Terminates launcher process on a connected device using ADB."
)
def task_stop_launcher() -> int:
	from subprocess import CalledProcessError, run
	try:
		run(GLOBALS.ADB_COMMAND + [
			"shell", "am",
			"force-stop", "com.zheka.horizon"
		], check=True, stdout=DEVNULL, stderr=DEVNULL)
		run(GLOBALS.ADB_COMMAND + [
			"shell", "am",
			"force-stop", "com.zhekasmirnov.innercore"
		], check=True, stdout=DEVNULL, stderr=DEVNULL)
	except CalledProcessError as err:
		return err.returncode
	return 0

@task(
	"configureADB",
	description="Adds a new connection to a mobile device/emulator via cable or network."
)
def task_configure_adb() -> int:
	from . import device
	device.setup_device_connection()
	return 0

### PROJECTS

@task(
	"newProject",
	description="Creates a project, prompting interactive input for name, template, and other properties."
)
def task_new_project() -> int:
	from .package import new_project

	index = new_project(GLOBALS.PREFERRED_CONFIG.get_value("defaultTemplate", "../toolchain-mod"))
	if index is None:
		return 1
	pretty_print_success("Successfully completed!")

	if not confirm_prompt("Select this project?", True):
		return 0
	GLOBALS.PROJECT_MANAGER.select_project(index=index)
	return 0

@task(
	"importProject",
	description="Converts a project for utilization with toolchains or creates a merge of several projects."
)
def task_import_project(path: str = "", target: str = "") -> int:
	pretty_print("Project successfully imported!")
	if not confirm_prompt("Select this project?", True):
		return 0
	GLOBALS.PROJECT_MANAGER.select_project(folder=relpath(path, GLOBALS.TOOLCHAIN_CONFIG.directory))
	return 0

@task(
	"removeProject",
	locks=["cleanup"],
	description="Removes a project, selected interactively by user."
)
def task_remove_project() -> int:
	if GLOBALS.PROJECT_MANAGER.how_much() == 0:
		abort("Not found any project to remove.")
	pretty_print("Selected project will be deleted forever, please think twice before removing anything!")

	who = GLOBALS.PROJECT_MANAGER.require_selection("Which project will be deleted?", "Do you really want to delete {}?", "I don't want it anymore")
	if not who:
		pretty_print("Nothing will happen.")
		return 0
	if GLOBALS.PROJECT_MANAGER.how_much() > 1 and not confirm_prompt("Do you really want to delete it?", True):
		return 0

	try:
		location = GLOBALS.TOOLCHAIN_CONFIG.get_path(who)
		GLOBALS.PROJECT_MANAGER.remove_project(folder=who)
		from .output_directory import get_temporary_directory, unique_folder_name
		from .package import pretty_cleanup_directory
		temporary_project_directory = join(get_temporary_directory(), "build", unique_folder_name(location))
		pretty_cleanup_directory(temporary_project_directory)
	except ValueError:
		abort(f"Folder {who!r} not found!")

	pretty_print("Project permanently deleted.")
	return 0

@task(
	"selectProject",
	description="Selects a project from a specified folder or requests interactive pickings from user."
)
def task_select_project(path: str = "") -> int:
	if len(path) > 0:
		where = GLOBALS.TOOLCHAIN_CONFIG.get_path(path)
		if isfile(where) and basename(where) == "make.json":
			where = dirname(where)
		if isdir(where):
			if where == GLOBALS.TOOLCHAIN_CONFIG.directory:
				abort("Requested path must be reference to project, not toolchain itself.")
			if not isfile(join(where, "make.json")):
				abort(f"Not found 'make.json' in {path!r}, it not belongs to project yet.")
			GLOBALS.PROJECT_MANAGER.select_project(folder=path)
			return 0
		else:
			abort(f"Requested project path {path!r} does not exists.")

	if GLOBALS.PROJECT_MANAGER.how_much() == 0:
		abort("Not found any project to choice.")

	who = GLOBALS.PROJECT_MANAGER.require_selection("Which project do you choice?", "Do you want to select {}?")
	if not who:
		GLOBALS.PROJECT_MANAGER.unselect_project()
		return 0
	try:
		GLOBALS.PROJECT_MANAGER.select_project(folder=who)
	except ValueError:
		abort(f"Folder {who!r} not found!")
	return 0

@task(
	"ensureProjectExists",
	description="Ensures that selected project is opened and exists."
)
def task_ensure_project_exists() -> int:
	if GLOBALS.is_project_available():
		return 0
	if GLOBALS.PROJECT_MANAGER.how_much() == 0:
		abort("Not found any project to choice.")

	who = GLOBALS.PROJECT_MANAGER.require_selection("Which project do you choice to continue?", "Do you want to select {} to continue?")
	if not who:
		pretty_print("Nothing will happen.")
		return 1
	try:
		GLOBALS.PROJECT_MANAGER.select_project(folder=who)
	except ValueError:
		abort(f"Folder {who!r} not found!")
	return 0

### MISCELLANEOUS

@task(
	"configureIde",
	description="Configures tasks in most useful IDEs for mods to use from the interface."
)
def task_configure_ide() -> int:
	from .workspace import (flush_compound_tasks, flush_shell_tasks,
	                        flush_vscode_compound_task, flush_vscode_shell_task)

	flush_shell_tasks("Select Project", "folder-opened", GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("python/select-project"), focus=True)
	flush_vscode_shell_task("Select Project by Active File", "repo-force-push", GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("python/select-project"), hidden=True, globbing="**/*", options=("${fileWorkspaceFolder}", ))
	flush_shell_tasks("Push", "rocket", GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("python/push"))
	flush_shell_tasks("Assemble Mod for Release", "archive", GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("python/assemble-release"))

	flush_shell_tasks("Build (No push)", "debug-all", GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("python/build-all"), hidden=True)
	flush_compound_tasks("Build", "debug-all", ("Build (No push)", "Push"))
	flush_vscode_compound_task("Build by Active File", "debug-all", ("Select Project by Active File", "Build"), hidden=True, globbing="**/*")

	flush_shell_tasks("Build Scripts and Resources (No push)", "debug-alt", GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("python/build-scripts-and-resources"), hidden=True)
	flush_compound_tasks("Build Scripts and Resources", "debug-alt", ("Build Scripts and Resources (No push)", "Push"))
	flush_vscode_compound_task("Build Scripts and Resources by Active File", "debug-alt", ("Select Project by Active File", "Build Scripts and Resources"), hidden=True, globbing="**/*")

	flush_shell_tasks("Build Java (No push)", "run-above", GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("python/compile-java"), hidden=True)
	flush_compound_tasks("Build Java", "run-above", ("Build Java (No push)", "Push"))
	flush_vscode_compound_task("Build Java by Active File", "run-above", ("Select Project by Active File", "Build Java"), hidden=True, globbing="**/*")

	flush_shell_tasks("Build Native (No push)", "run", GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("python/compile-native"), hidden=True)
	flush_compound_tasks("Build Native", "run", ("Build Native (No push)", "Push"))
	flush_vscode_compound_task("Build Native by Active File", "run", ("Select Project by Active File", "Build Native"), hidden=True, globbing="**/*")

	flush_shell_tasks("Watch Scripts (No push)", "debug-coverage", GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("python/watch-scripts"), hidden=True)
	flush_compound_tasks("Watch Scripts", "debug-coverage", ("Watch Scripts (No push)", "Push"))
	flush_vscode_compound_task("Watch Scripts by Active File", "debug-coverage", ("Select Project by Active File", "Watch Scripts"), hidden=True, globbing="**/*")

	flush_shell_tasks("Configure ADB", "device-mobile", GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("python/configure-adb"), focus=True)
	flush_shell_tasks("New Project", "new-folder", GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("python/new-project"), focus=True)
	flush_shell_tasks("Import Project", "repo-pull", GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("python/import-project"), focus=True)
	flush_shell_tasks("Remove Project", "root-folder-opened", GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("python/remove-project"), focus=True)
	flush_shell_tasks("Rebuild Declarations", "milestone", GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("python/rebuild-declarations"), hidden=True)
	flush_vscode_compound_task("Rebuild Declarations by Active File", "milestone", ("Select Project by Active File", "Rebuild Declarations"), hidden=True, globbing="**/*")
	flush_shell_tasks("Check for Updates", "cloud", GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("python/update-toolchain"), focus=True)
	flush_shell_tasks("Reinstall Components", "package", GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("python/component-integrity"), focus=True)
	flush_shell_tasks("Invalidate Caches", "flame", GLOBALS.TOOLCHAIN_CONFIG.get_relative_path("python/cleanup"), focus=True)

	return 0

@task(
	"updateToolchain",
	description="Updates the toolchain using a development branch; additionally verifies updates for installed components."
)
def task_update_toolchain() -> int:
	return 1

@task(
	"componentIntegrity",
	description="Installs additional components required for compilation or performs a initial setup."
)
def task_component_integrity(startup: bool = False) -> int:
	from . import component
	if startup:
		component.startup()
		return 0
	return component.upgrade()

@task(
	"cleanup",
	description="Clears cache of a selected project or all output files from previous builds, forgetting modified files."
)
def task_cleanup() -> int:
	from .package import pretty_cleanup_directory
	if GLOBALS.is_project_available():
		if confirm_prompt("Do you want to clear selected project cache?", True):
			pretty_cleanup_directory(GLOBALS.MAKE_CONFIG.get_build_path())
			pretty_cleanup_directory(GLOBALS.MOD_STRUCTURE.directory)
		return 0
	if not confirm_prompt("Do you want to clear all projects cache?", True):
		return 0
	from .output_directory import get_temporary_directory
	pretty_cleanup_directory(get_temporary_directory())
	return 0
