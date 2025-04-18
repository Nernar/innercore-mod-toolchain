import os
import time
from os.path import basename, isdir, join, relpath
from typing import Any, Dict, List, NoReturn, Optional

from . import GLOBALS
from .base_config import BaseConfig
from .shell import (Editable, Interactable, Selectable, abort, confirm_prompt,
                    error, get_toolchain_style, input_prompt, pretty_print,
                    select_prompt, warn)
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
	# if not template or not exists(GLOBALS.TOOLCHAIN_CONFIG.get_absolute_path(template)):
	# 	return new_project(template=select_template())
	# template_make_path = GLOBALS.TOOLCHAIN_CONFIG.get_absolute_path(template + "/template.json")
	# try:
	# 	with open(template_make_path, encoding="utf-8") as template_make:
	# 		template_config = BaseConfig(json.loads(template_make.read()))
	# except BaseException as err:
	# 	if len(GLOBALS.PROJECT_MANAGER.templates) > 1:
	# 		return new_project(None)
	# 	abort(f"Malformed '{template}/template.json', nothing to do.", cause=err)
	template_config = BaseConfig()

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
		if output_directory:
			create_interactable.interactable_text = f"Create in {output_directory}!"
			create_interactable.style = ""
		else:
			create_interactable.interactable_text = "Create..."
			create_interactable.style = "class:editable.hint"

	name_editable = Editable(
		"Name: ",
		text=GLOBALS.TOOLCHAIN_CONFIG.get_value("template.name", ""),
		hint=template_config.get_value("info.name"),
		on_text_changed=update_project_name
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
		focusable=Condition(lambda: output_directory is not None),
		on_interact=lambda _: app.exit(),
		add_interact_key_bindings=True,
		always_indent=True
	)
	contents.append(create_interactable)

	if not have_template or True: # XXX: TEST
		contents += [
			Window(height=1),
			Interactable("You can override template by setting `template` property in your 'toolchain.json', it will be automatically apply when you create a new project. Properties remain same as `info` property in 'make.json'.", style="class:editable.hint")
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
			ScrollablePane(
				HSplit(contents),
				scroll_offsets=ScrollOffsets(3, 3),
				display_arrows=False,
			)
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
		template or "XXX",
		output_directory,
		name_editable.get_value(fallback_allowed=True),
		author_editable.get_value(fallback_allowed=True),
		version_editable.get_value(fallback_allowed=True),
		description_editable.get_value(fallback_allowed=True),
		client_side_selectable.is_checked(),
	)

def new_project_stepwise(template: Optional[str] = "../toolchain-mod") -> Optional[int]:
	# if not template or not exists(GLOBALS.TOOLCHAIN_CONFIG.get_absolute_path(template)):
	# 	return new_project(template=select_template())
	# template_make_path = GLOBALS.TOOLCHAIN_CONFIG.get_absolute_path(template + "/template.json")
	# try:
	# 	with open(template_make_path, encoding="utf-8") as template_make:
	# 		template_config = BaseConfig(json.loads(template_make.read()))
	# except BaseException as err:
	# 	if len(GLOBALS.PROJECT_MANAGER.templates) > 1:
	# 		return new_project(None)
	# 	abort(f"Malformed '{template}/template.json', nothing to do.", cause=err)
	template_config = BaseConfig()

	have_template = GLOBALS.TOOLCHAIN_CONFIG.get_value("template") is not None
	always_skip_description = GLOBALS.TOOLCHAIN_CONFIG.get_value("template.skipDescription", False)

	ilya_moment = False
	output_directory = None
	project_name = None
	project_author = None
	project_version = None
	project_description = None
	is_client_side = False

	def update_project_name(input: Editable, explanation: Interactable) -> None:
		text = input.get_value(fallback_allowed=False)
		nonlocal output_directory
		if text:
			output_directory = get_project_folder_by_name(GLOBALS.TOOLCHAIN_CONFIG.directory, text)
		else:
			output_directory = None
		if output_directory:
			explanation.interactable_text = f"It will be created and located in {output_directory!r} directory."
		else:
			explanation.interactable_text = ""

	def do_next_step(step: int = -1) -> None:
		if step == -1:
			nonlocal ilya_moment
			ilya_moment = confirm_prompt("Are you Reider745?", fallback=False)
		elif step == 0:
			if len(GLOBALS.PROJECT_MANAGER.templates) > 1:
				nonlocal template
				template = select_prompt(
					"Which template should be used?",
					*GLOBALS.PROJECT_MANAGER.templates,
					fallback=0, returns_what=True
				)
		elif step == 1:
			nonlocal project_name
			project_name = input_prompt(
				"Decide a name for your project:" if not ilya_moment else "Name:",
				default_text=GLOBALS.TOOLCHAIN_CONFIG.get_value("template.name", ""),
				fallback=template_config.get_value("info.name", "Template Mod"),
				on_text_changed=update_project_name
			)
		elif step == 2:
			nonlocal project_author
			project_author = input_prompt(
				"Author who crafted this creation:" if not ilya_moment else "Author:",
				default_text=GLOBALS.TOOLCHAIN_CONFIG.get_value("template.author", ""),
				fallback=template_config.get_value("info.author")
			)
		elif step == 3:
			nonlocal project_version
			project_version = input_prompt(
				"What version a project starts from:" if not ilya_moment else "Version:",
				default_text=GLOBALS.TOOLCHAIN_CONFIG.get_value("template.version", ""),
				fallback=template_config.get_value("info.version", "1.0")
			)
		elif step == 4:
			nonlocal project_description
			project_description = input_prompt(
				"Describe this masterpiece in one sentence:" if not ilya_moment else "Description:",
				default_text=GLOBALS.TOOLCHAIN_CONFIG.get_value("template.description", ""),
				fallback=template_config.get_value("info.description")
			)
		elif step == 5:
			nonlocal is_client_side
			is_client_side = confirm_prompt(
				"Is it a client mod that not requires server?" if not ilya_moment else "Client side?",
				fallback=False
			)
		else:
			return
		do_next_step(step + 1)

	try:
		do_next_step()
	except KeyboardInterrupt or EOFError:
		pretty_print("Abort.")
		return None

	if not output_directory:
		assert project_name is not None
		output_directory = get_project_folder_by_name(GLOBALS.TOOLCHAIN_CONFIG.directory, project_name)
		if not output_directory:
			abort("Not found 'directory' property in observer!")
	if not have_template or True: # XXX: TEST
		pretty_print("You can override template by setting `template` property in your 'toolchain.json', it will be automatically apply when you create a new project. Properties remain same as `info` property in 'make.json'.", style="class:editable.hint")
	pretty_print(f"Copying template {template!r} to {output_directory!r}")

	return GLOBALS.PROJECT_MANAGER.create_project(
		template or "XXX",
		output_directory,
		project_name,
		project_author,
		project_version,
		project_description,
		is_client_side,
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
	return select_prompt(prompt, *variants, *additionals, selected_variant=selected, returns_what=True)
