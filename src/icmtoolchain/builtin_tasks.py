import subprocess
from os.path import dirname, isdir, isfile, join
from typing import Optional

from .context import GLOBALS, PROPERTIES
from .errors import abort
from .logger import attention, failure, frozen, success
from .output_directory import get_temporary_directory, unique_folder_name
from .shell import confirm_prompt
from .task import task
from .utils import DEVNULL

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
			attention("Property `debugAbi` has been deprecated in favor of configurations, determine your own ABIs via 'debug' rule.")
			abis = [abi]
	if not abis:
		abis = GLOBALS.MAKE_CONFIG.obtain_list("native.abis")
		if len(abis) == 0:
			abis = GLOBALS.MAKE_CONFIG.obtain_list("abis")
	if len(abis) == 0:
		attention(f"No `abis` value in 'toolchain.json' config, using defaults otherwise.")
		abis = ["arm64-v8a", "armeabi-v7a"]
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
		attention("Project uses configurable Gradle, different tools cannot be applied.")
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
		failure("You cannot have scripts to watch because your project does not support them.")
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
	overall_result = 0
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
		attention("Nothing to write in project configurations, project data does not exist.")
		return 0
	return project_data.flush_to_output(GLOBALS.PROJECT_STRUCTURE.directory)

@task(
	"clearOutput",
	locks=["assemble", "push", "native", "java", "resource", "script"],
	description="Optionally deletes the output folder; has no effect by default."
)
def task_clear_output(force: bool = False) -> int:
	if GLOBALS.MAKE_CONFIG.get_value("development.clearOutput", False) or force:
		GLOBALS.PROJECT_STRUCTURE.cleanup(clear_output=True)
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
	from .push import push_everything
	return push_everything()

@task(
	"launchApplication",
	description="Starts launcher with predefined autostart setting on a connected device using ADB."
)
def task_monkey_launcher() -> int:
	from .adb import ensure_device_ready
	if not ensure_device_ready():
		return 1

	preferred_launcher = GLOBALS.PREFERRED_CONFIG.get_value("adb.launcherPackage")
	preferred_activity = GLOBALS.PREFERRED_CONFIG.get_value("adb.launcherActivity")
	from .adb import (LAUNCHER_PACKAGES, launch_package_via_am,
	                  launch_package_via_monkey)
	packages = (preferred_launcher, ) if preferred_launcher else LAUNCHER_PACKAGES

	subprocess.run(GLOBALS.ADB_COMMAND + [
		"shell", "input",
		"keyevent", "KEYCODE_WAKEUP"
	], stdout=DEVNULL, stderr=DEVNULL)

	for package in packages:
		activity = preferred_activity
		if not activity and "horizon" in package:
			activity = "com.zhekasmirnov.horizon.activity.main.StartupWrapperActivity"

		launched = False
		if activity:
			launched = launch_package_via_am(package, activity)
		if not launched:
			launched = launch_package_via_monkey(package)

		if launched:
			success(f"Successfully launched {package!r}!")
			return 0

	failure("Horizon is not installed, nothing to launch.")
	return 1

@task(
	"stopApplication",
	description="Terminates launcher process on a connected device using ADB."
)
def task_stop_launcher() -> int:
	preferred_launcher = GLOBALS.PREFERRED_CONFIG.get_value("adb.launcherPackage")
	from .adb import LAUNCHER_PACKAGES
	packages = (preferred_launcher, ) if preferred_launcher else LAUNCHER_PACKAGES

	try:
		for package in packages:
			subprocess.run(GLOBALS.ADB_COMMAND + [
				"shell", "am", "force-stop", package
			], check=True, stdout=DEVNULL, stderr=DEVNULL)
	except subprocess.CalledProcessError as err:
		return err.returncode
	return 0

@task(
	"configureADB",
	description="Adds a new connection to a mobile device/emulator via cable or network."
)
def task_configure_adb() -> int:
	from .device_setup import setup_device_connection
	setup_device_connection()
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
	success("Successfully completed!")

	if not confirm_prompt("Select this project?", True):
		return 0
	GLOBALS.PROJECT_MANAGER.select_project(index=index)
	return 0

@task(
	"removeProject",
	locks=["cleanup"],
	description="Removes a project, selected interactively by user."
)
def task_remove_project() -> int:
	if GLOBALS.PROJECT_MANAGER.how_much() == 0:
		abort("Not found any project to remove.")
	attention("Selected project will be deleted forever, please think twice before removing anything!")

	who = GLOBALS.PROJECT_MANAGER.require_selection("Which project will be deleted?", "Do you really want to delete {}?", "I don't want it anymore")
	if not who:
		frozen("Nothing will happen.")
		return 0
	if GLOBALS.PROJECT_MANAGER.how_much() > 1 and not confirm_prompt("Do you really want to delete it?", True):
		return 0

	try:
		location = GLOBALS.TOOLCHAIN_CONFIG.get_path(who)
		GLOBALS.PROJECT_MANAGER.remove_project(folder=who)
		from .package import pretty_cleanup_directory
		temporary_project_directory = join(get_temporary_directory(), "build", unique_folder_name(location))
		pretty_cleanup_directory(temporary_project_directory)
	except ValueError:
		abort(f"Folder {who!r} not found!")

	success("Project permanently deleted.")
	return 0

@task(
	"selectProject",
	description="Selects a project from a specified folder or requests interactive pickings from user."
)
def task_select_project(path: str = "") -> int:
	if len(path) > 0:
		where = GLOBALS.TOOLCHAIN_CONFIG.get_path(path)
		if isfile(where): # and basename(where) == "make.json"
			where = dirname(where)
		if isdir(where):
			if where == GLOBALS.TOOLCHAIN_CONFIG.directory:
				abort("Requested path must be reference to project, not toolchain itself.")
			# if not isfile(join(where, "make.json")):
				# abort(f"Not found 'make.json' in {path!r}, it not belongs to project yet.")
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
		frozen("Nothing will happen.")
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
	from .workspace import (flush_compound_tasks, flush_toolchain_tasks,
	                        flush_vscode_compound_task)

	# flush_toolchain_tasks("Select Project", "folder-opened", "selectProject", focus=True)
	# flush_vscode_toolchain_task("Select Project by Active File", "repo-force-push", "selectProject --path", hidden=True, glob="**/*", options=("${fileWorkspaceFolder}", ))
	flush_toolchain_tasks("Push", "rocket", "ensureProjectExists stopApplication pushEverything launchApplication")
	flush_toolchain_tasks("Assemble Mod for Release", "archive", "--release ensureProjectExists clearOutput --force buildScripts compileNative compileJava buildResources buildInfo buildPackage")

	flush_toolchain_tasks("Build (No push)", "debug-all", "ensureProjectExists clearOutput buildScripts compileNative compileJava buildResources buildInfo", hidden=True)
	flush_compound_tasks("Build", "debug-all", ("Build (No push)", "Push"))
	flush_vscode_compound_task("Build by Active File", "debug-all", ("Select Project by Active File", "Build"), hidden=True, glob="**/*")

	flush_toolchain_tasks("Build Scripts and Resources (No push)", "debug-alt", "ensureProjectExists clearOutput buildScripts buildResources buildInfo", hidden=True)
	flush_compound_tasks("Build Scripts and Resources", "debug-alt", ("Build Scripts and Resources (No push)", "Push"))
	flush_vscode_compound_task("Build Scripts and Resources by Active File", "debug-alt", ("Select Project by Active File", "Build Scripts and Resources"), hidden=True, glob="**/*")

	flush_toolchain_tasks("Build Java (No push)", "run-above", "ensureProjectExists compileJava buildInfo", hidden=True)
	flush_compound_tasks("Build Java", "run-above", ("Build Java (No push)", "Push"))
	flush_vscode_compound_task("Build Java by Active File", "run-above", ("Select Project by Active File", "Build Java"), hidden=True, glob="**/*")

	flush_toolchain_tasks("Build Native (No push)", "run", "ensureProjectExists compileNative buildInfo", hidden=True)
	flush_compound_tasks("Build Native", "run", ("Build Native (No push)", "Push"))
	flush_vscode_compound_task("Build Native by Active File", "run", ("Select Project by Active File", "Build Native"), hidden=True, glob="**/*")

	# flush_toolchain_tasks("Watch Scripts (No push)", "debug-coverage", "ensureProjectExists clearOutput watchScripts buildInfo", hidden=True)
	# flush_compound_tasks("Watch Scripts", "debug-coverage", ("Watch Scripts (No push)", "Push"))
	# flush_vscode_compound_task("Watch Scripts by Active File", "debug-coverage", ("Select Project by Active File", "Watch Scripts"), hidden=True, glob="**/*")

	flush_toolchain_tasks("Rebuild Declarations", "milestone", "ensureProjectExists updateIncludes", hidden=True)
	flush_vscode_compound_task("Rebuild Declarations by Active File", "milestone", ("Select Project by Active File", "Rebuild Declarations"), hidden=True, glob="**/*")
	flush_toolchain_tasks("Invalidate Caches", "flame", "cleanup", focus=True)

	flush_toolchain_tasks("New Project", "new-folder", "newProject", focus=True)
	# flush_toolchain_tasks("Import Project", "repo-pull", "importProject", focus=True)
	# XXX: flush_toolchain_tasks("Remove Project", "root-folder-opened", "removeProject", focus=True)
	# flush_toolchain_tasks("Check for Updates", "cloud", "updateToolchain", focus=True)
	flush_toolchain_tasks("Configure ADB", "device-mobile", "configureADB", focus=True)
	# flush_toolchain_tasks("Reinstall Components", "package", "componentIntegrity", focus=True)

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
	if startup:
		from .component import startup as component_task
	else:
		from .component import upgrade as component_task
	component_task()
	return 0

@task(
	"cleanup",
	description="Clears cache of a selected project or all output files from previous builds, forgetting modified files."
)
def task_cleanup() -> int:
	from .package import pretty_cleanup_directory
	if GLOBALS.is_project_available():
		if confirm_prompt("Do you want to clear selected project cache?", True):
			pretty_cleanup_directory(GLOBALS.MAKE_CONFIG.get_build_path())
			GLOBALS.PROJECT_STRUCTURE.cleanup(clear_output=True)
		return 0
	if not confirm_prompt("Do you want to clear all projects cache?", True):
		return 0
	pretty_cleanup_directory(get_temporary_directory())
	return 0
