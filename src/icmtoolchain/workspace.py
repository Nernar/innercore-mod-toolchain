import json
import posixpath
from os.path import basename, isfile, join, relpath
from re import sub
from typing import Callable, Collection, Optional

from .config import FileConfig
from .context import GLOBALS
from .utils import ensure_directory, ensure_file_directory


class WorkspaceNotAvailable(RuntimeError):
	def __init__(self, *args: object) -> None:
		RuntimeError.__init__(self, "Workspace is not available!", *args)

class CodeWorkspace(FileConfig):
	def __init__(self, path: str) -> None:
		try:
			super().__init__(path)
			self.valid = True
		except ValueError as exc:
			from .logger import attention
			attention(f"Malformed {basename(path)!r}, ignoring it: {exc}.")
			self.valid = False

	def available(self) -> bool:
		return self.valid and isfile(self.path)

	def get_relative_path(self, path_from_config: str) -> str:
		if not self.available():
			raise WorkspaceNotAvailable()
		return super().get_relative_path(path_from_config=path_from_config)

	def get_toolchain_path(self, relative_path: str = "") -> str:
		if not self.available():
			raise WorkspaceNotAvailable()
		return relpath(GLOBALS.TOOLCHAIN_CONFIG.get_relative_path(relative_path), self.directory)

	def save_as_file(self, output_path: Optional[str] = None) -> None:
		if not self.available():
			raise WorkspaceNotAvailable()
		super().save_as_file(output_path=output_path)

class WorkspaceBuildConfiguration:
	@staticmethod
	def get_vscode_task(name: str, icon: str, **kwargs):
		task = dict()
		task.update({
			"label": name,
			"icon": {
				"id": icon
			}
		})
		if "hidden" in kwargs and kwargs["hidden"]:
			task["hide"] = True
		if "focus" in kwargs and kwargs["focus"]:
			task["presentation"] = {
				"focus": True
			}
		task.update({
			"group": {
				"kind": "build",
				"isDefault": True
			},
			"problemMatcher": list()
		})
		if "glob" in kwargs:
			task["group"]["glob"] = kwargs["glob"]
		return task

	@staticmethod
	def get_vscode_shell_task(name: str, icon: str, path: str, **kwargs):
		task = WorkspaceBuildConfiguration.get_vscode_task(name, icon, **kwargs)
		absolute_path = GLOBALS.MAKE_CONFIG.get_path_to_config(path).replace("\\", "/")
		absolute_path = absolute_path if absolute_path.startswith("..") else "./" + absolute_path
		task.update({
			"type": "shell",
			"command": f"./{basename(path)}.sh",
			"options": {
				"cwd": posixpath.dirname(absolute_path)
			}
		})
		task["windows"] = {
			"command": task["command"][:-3].replace("/", "\\") + ".bat",
			"options": {
				"cwd": task["options"]["cwd"].replace("/", "\\")
			}
		}
		if "options" in kwargs:
			task["args"] = kwargs["options"]
		return task

	@staticmethod
	def get_vscode_toolchain_task(name: str, icon: str, cmd: str, **kwargs):
		task = WorkspaceBuildConfiguration.get_vscode_task(name, icon, **kwargs)
		task.update({
			"type": "shell",
			"command": f"icmtoolchain {cmd}"
		})
		if "options" in kwargs:
			task["args"] = kwargs["options"]
		return task

	@staticmethod
	def get_vscode_compound_task(name: str, icon: str, order: Collection[str], **kwargs):
		task = WorkspaceBuildConfiguration.get_vscode_task(name, icon, **kwargs)
		task.update({
			"dependsOn": order,
			"dependsOrder": "sequence"
		})
		if not "presentation" in task:
			task["presentation"] = {}
		task["presentation"].update({
			"panel": "shared",
			"showReuseMessage": False
		})
		return task

	@staticmethod
	def flush_vscode_task(name: str, icon: str, method: Callable, *args, **kwargs):
		tasks_path = GLOBALS.MAKE_CONFIG.get_relative_path(join(".vscode", "tasks.json"))
		ensure_file_directory(tasks_path)
		configuration: dict = method(name, icon, *args, **kwargs)

		definition = None
		if isfile(tasks_path):
			with open(tasks_path, encoding="utf-8") as tasks:
				definition = json.load(tasks)
		if not isinstance(definition, dict):
			definition = {}
			definition["version"] = "2.0.0"
		if "tasks" not in definition:
			definition["tasks"] = list()

		duplicates = list()
		for task in definition["tasks"]:
			if "label" in task and task["label"] == name:
				duplicates.append(task)
		for task in duplicates:
			definition["tasks"].remove(task)

		definition["tasks"].append(configuration)
		with open(tasks_path, "w", encoding="utf-8") as tasks:
			json.dump(definition, tasks, indent="\t", ensure_ascii=False)
			tasks.write("\n")

	@staticmethod
	def get_idea_task(name: str, type: str, **kwargs):
		from xml.dom import minidom
		document = minidom.Document()
		component = document.createElement("component")
		component.setAttribute("name", "ProjectRunConfigurationManager")

		configuration = document.createElement("configuration")
		configuration.setAttribute("name", name[:-7] if name.endswith(" (Unix)") else name)
		configuration.setAttribute("default", "false")
		configuration.setAttribute("type", type)
		if "focus" in kwargs and kwargs["focus"]:
			configuration.setAttribute("focusToolWindowBeforeRun", "true")
		component.appendChild(configuration)

		method = document.createElement("method")
		method.setAttribute("v", "2")
		configuration.appendChild(method)

		return component

	@staticmethod
	def get_idea_shell_task(name: str, path: str, **kwargs):
		from xml.dom import minidom
		component = WorkspaceBuildConfiguration.get_idea_task(name, "ShConfigurationType", **kwargs)
		configuration: minidom.Node = component.childNodes[0]
		assert component.ownerDocument is not None
		document: minidom.Document = component.ownerDocument
		relative_path = GLOBALS.MAKE_CONFIG.get_path_to_config(path)
		relative_path = "$PROJECT_DIR$/" + relative_path.replace("\\", "/")

		script_path = document.createElement("option")
		script_path.setAttribute("name", "SCRIPT_PATH")
		script_path.setAttribute("value", relative_path)
		configuration.appendChild(script_path)
		script_options = document.createElement("option")
		script_options.setAttribute("name", "SCRIPT_OPTIONS")
		script_options.setAttribute("value", " ".join(kwargs["options"]) if "options" in kwargs else "")
		configuration.appendChild(script_options)
		independent_script_path = document.createElement("option")
		independent_script_path.setAttribute("name", "INDEPENDENT_SCRIPT_PATH")
		independent_script_path.setAttribute("value", "false")
		configuration.appendChild(independent_script_path)

		script_working_directory = document.createElement("option")
		script_working_directory.setAttribute("name", "SCRIPT_WORKING_DIRECTORY")
		script_working_directory.setAttribute("value", posixpath.dirname(relative_path))
		configuration.appendChild(script_working_directory)
		independent_script_working_directory = document.createElement("option")
		independent_script_working_directory.setAttribute("name", "INDEPENDENT_SCRIPT_WORKING_DIRECTORY")
		independent_script_working_directory.setAttribute("value", "false")
		configuration.appendChild(independent_script_working_directory)

		return component

	@staticmethod
	def get_idea_toolchain_task(name: str, cmd: str, **kwargs):
		from xml.dom import minidom
		component = WorkspaceBuildConfiguration.get_idea_task(name, "ShConfigurationType", **kwargs)
		configuration: minidom.Node = component.childNodes[0]
		assert component.ownerDocument is not None
		document: minidom.Document = component.ownerDocument

		script_path = document.createElement("option")
		script_path.setAttribute("name", "SCRIPT_TEXT")
		script_path.setAttribute("value", f"icmtoolchain {cmd}")
		configuration.appendChild(script_path)
		script_options = document.createElement("option")
		script_options.setAttribute("name", "SCRIPT_OPTIONS")
		script_options.setAttribute("value", " ".join(kwargs["options"]) if "options" in kwargs else "")
		configuration.appendChild(script_options)
		independent_script_path = document.createElement("option")
		independent_script_path.setAttribute("name", "INDEPENDENT_SCRIPT_PATH")
		independent_script_path.setAttribute("value", "true")
		configuration.appendChild(independent_script_path)

		script_working_directory = document.createElement("option")
		script_working_directory.setAttribute("name", "SCRIPT_WORKING_DIRECTORY")
		script_working_directory.setAttribute("value", "$PROJECT_DIR$")
		configuration.appendChild(script_working_directory)
		independent_script_working_directory = document.createElement("option")
		independent_script_working_directory.setAttribute("name", "INDEPENDENT_SCRIPT_WORKING_DIRECTORY")
		independent_script_working_directory.setAttribute("value", "true")
		configuration.appendChild(independent_script_working_directory)

		execute_file = document.createElement("option")
		execute_file.setAttribute("name", "EXECUTE_SCRIPT_FILE")
		execute_file.setAttribute("value", "false")
		configuration.appendChild(execute_file)

		return component

	@staticmethod
	def get_idea_compound_task(name: str, order: Collection[str], **kwargs):
		from xml.dom import minidom
		component = WorkspaceBuildConfiguration.get_idea_task(name, "CompoundRunConfigurationType", **kwargs)
		assert component.ownerDocument is not None
		document: minidom.Document = component.ownerDocument
		configuration: minidom.Node = component.childNodes[0]

		for task_name in order:
			to_run = document.createElement("toRun")
			to_run.setAttribute("name", task_name)
			to_run.setAttribute("type", "ShConfigurationType")
			configuration.appendChild(to_run)

		return component

	@staticmethod
	def flush_idea_task(name: str, method: Callable, *args, **kwargs):
		from xml.dom import minidom
		configurations_path = GLOBALS.MAKE_CONFIG.get_relative_path(join(".idea", "runConfigurations"))
		ensure_directory(configurations_path)
		component: minidom.Node = method(name, *args, **kwargs)
		unescaped_name = sub(r"\W", "_", name) + ".xml"
		with open(join(configurations_path, unescaped_name), "w", encoding="utf-8") as task:
			task.write(component.toprettyxml(indent=" " * 2))

# def flush_vscode_shell_task(name: str, icon: str, path: str, **kwargs):
# 	WorkspaceBuildConfiguration.flush_vscode_task(name, icon, WorkspaceBuildConfiguration.get_vscode_shell_task, path, **kwargs)

def flush_vscode_toolchain_task(name: str, icon: str, cmd: str, **kwargs):
	WorkspaceBuildConfiguration.flush_vscode_task(name, icon, WorkspaceBuildConfiguration.get_vscode_toolchain_task, cmd, **kwargs)

def flush_vscode_compound_task(name: str, icon: str, order: Collection[str], **kwargs):
	WorkspaceBuildConfiguration.flush_vscode_task(name, icon, WorkspaceBuildConfiguration.get_vscode_compound_task, order, **kwargs)

# def flush_idea_shell_task(name: str, path: str, **kwargs):
# 	WorkspaceBuildConfiguration.flush_idea_task(name, WorkspaceBuildConfiguration.get_idea_shell_task, path + ".bat", **kwargs)
# 	WorkspaceBuildConfiguration.flush_idea_task(f"{name} (Unix)", WorkspaceBuildConfiguration.get_idea_shell_task, path + ".sh", **kwargs)

def flush_idea_toolchain_task(name: str, cmd: str, **kwargs):
	WorkspaceBuildConfiguration.flush_idea_task(name, WorkspaceBuildConfiguration.get_idea_toolchain_task, cmd, **kwargs)

def flush_idea_compound_task(name: str, order: Collection[str], **kwargs):
	WorkspaceBuildConfiguration.flush_idea_task(name, WorkspaceBuildConfiguration.get_idea_compound_task, order, **kwargs)

# def flush_shell_tasks(name: str, icon: str, path: str, **kwargs):
# 	flush_vscode_shell_task(name, icon, path, **kwargs)
# 	flush_idea_shell_task(name, path, **kwargs)

def flush_toolchain_tasks(name: str, icon: str, cmd: str, **kwargs):
	flush_vscode_toolchain_task(name, icon, cmd, **kwargs)
	flush_idea_toolchain_task(name, cmd, **kwargs)

def flush_compound_tasks(name: str, icon: str, order: Collection[str], **kwargs):
	flush_vscode_compound_task(name, icon, order, **kwargs)
	flush_idea_compound_task(name, order, **kwargs)
