import json
import os
import time
from os.path import basename, exists, isdir, join, relpath
from typing import Any, Dict, List, Optional, cast

from . import GLOBALS
from .base_config import BaseConfig
from .shell import (abort, error, pretty_print, pretty_print_attention,
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

def new_project(template: Optional[str] = "../toolchain-mod") -> Optional[int]:
	have_template = GLOBALS.TOOLCHAIN_CONFIG.has_value("template")
	always_skip_description = GLOBALS.TOOLCHAIN_CONFIG.get_value("template.skipDescription", False)
	output_directory = None

	pretty_print("Create new project")
	from .prompt import Confirm, Feedback, Input, Review, Select

	def on_validate_template(template: str, select: Optional[Select] = None) -> bool:
		template_make_path = GLOBALS.TOOLCHAIN_CONFIG.get_absolute_path(template + "/template.json")
		try:
			with open(template_make_path, encoding="utf-8") as template_make:
				template_config = BaseConfig(json.loads(template_make.read()))
		except BaseException as exc:
			if select is not None:
				select.explanation = f"Malformed '{template}/template.json', nothing to do."
				return False
			if len(GLOBALS.PROJECT_MANAGER.templates) == 0 or template == GLOBALS.PROJECT_MANAGER.templates[0]:
				abort(f"Malformed '{template}/template.json', nothing to do.", cause=exc)
			template_config = BaseConfig()
		update_template_defaults(template_config)
		return True

	def create_template_chooser() -> Optional[Select]:
		nonlocal template
		if template and exists(GLOBALS.TOOLCHAIN_CONFIG.get_absolute_path(template)):
			on_validate_template(template)
		elif len(GLOBALS.PROJECT_MANAGER.templates) <= 1:
			if len(GLOBALS.PROJECT_MANAGER.templates) == 0:
				pretty_print_attention("You need at least one template to create a project, it can be done by creating a folder and renaming `make.json` to `template.json`.")
				abort("Not found any templates, nothing to do.")
			template = GLOBALS.PROJECT_MANAGER.templates[0]
			on_validate_template(template)
		if len(GLOBALS.PROJECT_MANAGER.templates) == 0 or template == GLOBALS.PROJECT_MANAGER.templates[0]:
			return None
		template_locations = GLOBALS.PROJECT_MANAGER.templates.copy()
		if template and not template in template_locations:
			template_locations.insert(0, template)
		return Select(
			"Which template should be used?",
			variants=template_locations,
			default_variant=template,
			on_focus=lambda select, index, key, control: setattr(select, "explanation", None),
			on_accept=lambda select, index, key, control: on_validate_template(key, select),
			returns_what=True
		)

	def update_project_name(input: Input, text: str) -> None:
		nonlocal output_directory
		result_with_fallback = text or input.default_text or input.hint
		if result_with_fallback:
			output_directory = get_project_folder_by_name(GLOBALS.TOOLCHAIN_CONFIG.directory, result_with_fallback)
		else:
			output_directory = None
		if text and output_directory:
			input.explanation = f"It will be created and located in {output_directory!r} directory."
		else:
			input.explanation = ""

	default_name = GLOBALS.TOOLCHAIN_CONFIG.get_value("template.name")
	create_review = Review(
		template=create_template_chooser(),
		name=Input("Decide a name for your project:", on_input=update_project_name, default_text=default_name, hint="Template Mod"),
		author=Input("Author who crafted this creation:", default_text=GLOBALS.TOOLCHAIN_CONFIG.get_value("template.author")),
		version=Input("What version a project starts from:", default_text=GLOBALS.TOOLCHAIN_CONFIG.get_value("template.version"), hint="1.0"),
		description=Input("Describe this masterpiece in one sentence:", default_text=GLOBALS.TOOLCHAIN_CONFIG.get_value("template.description")),
		client_side=Confirm("Is this mod client-side (without server requirement)?", default_value=GLOBALS.TOOLCHAIN_CONFIG.get_value("template.clientOnly", False))
	)

	def update_template_defaults(template_config: BaseConfig) -> None:
		name = cast(Input, create_review.require_feedback("name"))
		name.hint = template_config.get_value("info.name", "Template Mod")
		author = cast(Input, create_review.require_feedback("author"))
		author.hint = template_config.get_value("info.author")
		version = cast(Input, create_review.require_feedback("version"))
		version.hint = template_config.get_value("info.version", "1.0")
		description = cast(Input, create_review.require_feedback("description"))
		description.hint = template_config.get_value("info.description")
		client_side = cast(Confirm, create_review.require_feedback("client_side"))
		client_side.default_value = GLOBALS.TOOLCHAIN_CONFIG.get_value("template.clientOnly", template_config.get_value("info.clientOnly", False))

	def on_request_feedback(review: Review, key: str, feedback: Feedback) -> bool:
		if always_skip_description and key in ("author", "version", "description", "client_side"):
			feedback.on_pre_request = lambda _: feedback.application.exit()
		return True
	create_review.on_request_feedback = on_request_feedback

	update_project_name(cast(Input, create_review.require_feedback("name")), default_name or "")

	results = create_review.request_safe(returns_empty_properties=True)
	if results is None:
		return None
	assert output_directory is not None
	choosen_template = results["template"] or "../toolchain-mod"
	if always_skip_description:
		pretty_print_attention("Property `template.skipDescription` has disabled some options.")
	elif not have_template:
		pretty_print("You can override template by setting `template` property in your 'toolchain.json', it will be automatically apply when you create a new project. Properties remain same as `info` property in 'make.json'.", style="class:editable.hint")

	pretty_print(f"Copying template {choosen_template!r} to {output_directory!r}")
	return GLOBALS.PROJECT_MANAGER.create_project(
		choosen_template,
		output_directory,
		name=results["name"],
		author=results["author"],
		version=results["version"],
		description=results["description"],
		clientOnly=results["client_side"]
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
