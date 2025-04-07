import json
import os
import time
from os.path import basename, exists, isdir, join, relpath
from typing import Any, Dict, List, NoReturn, Optional

from . import GLOBALS
from .base_config import BaseConfig
from .shell import (Editable, Interactable, Selectable, abort, error,
                    get_toolchain_style, pretty_print, select_prompt, warn)
from .utils import (copy_file, ensure_not_whitespace, get_all_files,
                    get_project_folder_by_name, name_to_identifier,
                    remove_tree)


def get_path_set(locations: List[str], error_sensitive: bool = False) -> Optional[List[str]]:
	directories = list()
	for path in locations:
		for directory in GLOBALS.MAKE_CONFIG.get_paths(path):
			if isdir(directory):
				directories.append(directory)
			else:
				if error_sensitive:
					error(f"Declared invalid directory {path}, task will be terminated!")
					return None
				else:
					warn(f"* Declared invalid directory {path}, it will be skipped.")
	return directories

def cleanup_relative_directory(path: str, absolute: bool = False) -> None:
	start_time = time.time()
	remove_tree(path if absolute else GLOBALS.TOOLCHAIN_CONFIG.get_path(path))
	pretty_print(f"Completed {basename(path)} cleanup in {int((time.time() - start_time) * 100) / 100}s")

def select_template() -> Optional[str]:
	if len(GLOBALS.PROJECT_MANAGER.templates) <= 1:
		if len(GLOBALS.PROJECT_MANAGER.templates) == 0:
			error("Please, ensure that `projectLocations` property in your 'toolchain.json' contains any folder with 'template.json'.")
			abort("Not found any templates, nothing to do.")
		return GLOBALS.PROJECT_MANAGER.templates[0]
	return select_prompt(
		"Which template do you want?",
		*GLOBALS.PROJECT_MANAGER.templates,
		fallback=0, returns_what=True
	)

def new_project(template: Optional[str] = "../toolchain-mod") -> Optional[int]:
	if not template or not exists(GLOBALS.TOOLCHAIN_CONFIG.get_absolute_path(template)):
		return new_project(template=select_template())
	template_make_path = GLOBALS.TOOLCHAIN_CONFIG.get_absolute_path(template + "/template.json")
	try:
		with open(template_make_path, encoding="utf-8") as template_make:
			template_config = BaseConfig(json.loads(template_make.read()))
	except BaseException as err:
		if len(GLOBALS.PROJECT_MANAGER.templates) > 1:
			return new_project(None)
		abort(f"Malformed '{template}/template.json', nothing to do.", cause=err)

	have_template = GLOBALS.TOOLCHAIN_CONFIG.get_value("template") is not None
	always_skip_description = GLOBALS.TOOLCHAIN_CONFIG.get_value("template.skipDescription", False)

	from prompt_toolkit import Application
	from prompt_toolkit.buffer import Buffer
	from prompt_toolkit.filters import Condition
	from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
	from prompt_toolkit.key_binding.bindings.focus import (focus_next,
	                                                       focus_previous)
	from prompt_toolkit.keys import Keys
	from prompt_toolkit.layout import (HSplit, Layout, ScrollablePane,
	                                   ScrollOffsets, Window)
	from prompt_toolkit.layout.processors import AfterInput, ConditionalProcessor
	contents = [
		Interactable("Create new project"),
		Window(height=1),
	]

	if len(GLOBALS.PROJECT_MANAGER.templates) > 1:
		contents.append(
			Interactable("Choose template", focusable=True, on_interact=lambda _: app.exit(result="template"), add_interact_key_bindings=True)
		)

	output_directory = None

	def update_project_name(buffer: Buffer) -> None:
		nonlocal output_directory
		output_directory = get_project_folder_by_name(GLOBALS.TOOLCHAIN_CONFIG.directory, buffer.text)
		create_interactable.style = "" if output_directory is not None else "class:print.answer"

	name_editable = Editable(
		"Name: ",
		text=GLOBALS.TOOLCHAIN_CONFIG.get_value("template.name", ""),
		hint=template_config.get_value("info.name"),
		on_text_changed=update_project_name,
		input_processors=[
			ConditionalProcessor(
				AfterInput(lambda: f" in {output_directory}", style="class:print.answer"),
				Condition(lambda: output_directory is not None)
			)
		]
	)
	contents.append(name_editable)

	author_editable = Editable(
		"Author: ",
		text=GLOBALS.TOOLCHAIN_CONFIG.get_value("template.author", ""),
		hint=template_config.get_value("info.author")
	)
	version_editable = Editable(
		"Version: ",
		text=GLOBALS.TOOLCHAIN_CONFIG.get_value("template.version", ""),
		hint=template_config.get_value("info.version", "1.0")
	)
	description_editable = Editable(
		"Description: ",
		text=GLOBALS.TOOLCHAIN_CONFIG.get_value("template.description", ""),
		hint=template_config.get_value("info.description")
	)
	client_side_selectable = Selectable(
		"Client side only",
		checked=GLOBALS.TOOLCHAIN_CONFIG.get_value(
			"template.clientOnly",
			template_config.get_value("info.clientOnly", False)
		)
	)
	if not always_skip_description:
		contents += [
			author_editable,
			version_editable,
			description_editable,
			client_side_selectable
		]
	create_interactable = Interactable(
		"Create!",
		focusable=Condition(lambda: output_directory is not None),
		on_interact=lambda _: app.exit(),
		add_interact_key_bindings=True,
		always_indent=True
	)
	contents.append(create_interactable)
	if not have_template:
		contents += [
			Window(height=1),
			Interactable("You can override template by setting `template` property in your 'toolchain.json', it will be automatically apply when you create a new project. Properties remain same as `info` property in 'make.json'.")
		]
	update_project_name(name_editable.buffer)

	bindings = KeyBindings()
	bindings.add(Keys.Down)(focus_next)
	bindings.add(Keys.Up)(focus_previous)

	@bindings.add("c-c")
	@bindings.add("<sigint>")
	def _(event: KeyPressEvent) -> NoReturn:
		event.app.exit()
		raise KeyboardInterrupt()

	app = Application(
		layout=Layout(
			HSplit([
				Interactable("Inner Core Mod Toolchain"),
				ScrollablePane(
					HSplit(contents),
					scroll_offsets=ScrollOffsets(3, 3),
					display_arrows=False,
				)
			])
		),
		style=get_toolchain_style(),
		include_default_pygments_style=False,
		key_bindings=bindings,
		full_screen=False,
		mouse_support=True,
		erase_when_done=True,
	)

	try:
		result = app.run()
		if result == "template":
			return new_project(None)
	except KeyboardInterrupt or EOFError:
		pretty_print("Abort.")
		return None

	if not output_directory:
		abort("Not found 'directory' property in observer!")
	pretty_print(f"Copying template {template!r} to {output_directory!r}")

	return GLOBALS.PROJECT_MANAGER.create_project(
		template,
		output_directory,
		name_editable.get_value(fallback_allowed=True),
		author_editable.get_value(fallback_allowed=True),
		version_editable.get_value(fallback_allowed=True),
		description_editable.get_value(fallback_allowed=True),
		client_side_selectable.is_checked(),
	)

def resolve_make_format_map(make_obj: Dict[Any, Any], path: str) -> Dict[Any, Any]:
	make_obj_info = make_obj["info"] if "info" in make_obj else dict()
	identifier = name_to_identifier(basename(path))
	while len(identifier) > 0 and identifier[0].isdecimal():
		identifier = identifier[1:]
	package_prefix = name_to_identifier(make_obj_info["author"]) if "author" in make_obj_info else "icmods"
	while len(package_prefix) > 0 and package_prefix[0].isdecimal():
		package_prefix = package_prefix[1:]
	package_suffix = name_to_identifier(make_obj_info["name"]) if "name" in make_obj_info else identifier
	while len(package_suffix) > 0 and package_suffix[0].isdecimal():
		package_suffix = package_suffix[1:]
	return {
		"identifier": ensure_not_whitespace(identifier, "whoami"),
		"packageSuffix": ensure_not_whitespace(package_suffix, "mod"),
		"packagePrefix": package_prefix,
		**make_obj_info,
		"clientOnly": "true" if "clientOnly" in make_obj_info and make_obj_info["clientOnly"] else "false"
	}

def setup_project(make_obj: Dict[Any, Any], template: str, path: str) -> None:
	makemap = resolve_make_format_map(make_obj, path)
	dirmap = { template: "" }
	for dirpath, dirnames, filenames in os.walk(template):
		for dirname in dirnames:
			dir = join(dirpath, dirname)
			dirmap[dir] = relpath(dir, template)
			try:
				dirmap[dir] = dirmap[dir].format_map(makemap)
			except BaseException:
				warn(f"* Source {dirmap[dir]!r} contains malformed name!")
			os.mkdir(join(path, dirmap[dir]))
		for filename in filenames:
			if dirpath == template and filename == "template.json":
				continue
			file = join(path, join(dirmap[dirpath], filename))
			copy_file(join(dirpath, filename), file)
	for source in get_all_files(path, extensions=(".json", ".js", ".ts", "manifest", ".java", ".cpp")):
		with open(source, "r", encoding="utf-8") as source_file:
			lines = source_file.readlines()
		for index in range(len(lines)):
			try:
				lines[index] = lines[index].format_map(makemap)
			except BaseException:
				pass
		with open(source, "w", encoding="utf-8") as source_file:
			source_file.writelines(lines)

def select_project(variants: List[str], prompt: Optional[str] = "Which project do you want?", selected: Optional[str] = None, *additionals: str) -> Optional[str]:
	project_count = len(variants)

	def shortcut_transformer(directory: str, offset: int):
		if offset >= project_count:
			return directory
		text = GLOBALS.PROJECT_MANAGER.get_shortcut(directory)
		from prompt_toolkit.formatted_text import to_formatted_text
		return to_formatted_text(text, style="class:selection") if directory == selected else text

	return select_prompt(prompt, *variants, *additionals, text_transformer=shortcut_transformer, returns_what=True)
