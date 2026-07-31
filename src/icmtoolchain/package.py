import json
import os
import time
from os.path import basename, exists, isdir, isfile, join, relpath
from typing import Any, Dict, List, Optional, cast

from .config import Config, FileConfig
from .context import GLOBALS
from .errors import abort
from .logger import attention, failure, print, success
from .output_directory import expand_paths
from .shell import confirm_prompt, select_prompt
from .utils import (copy_file, ensure_not_whitespace, get_all_files,
                    get_project_folder_by_name, name_to_identifier,
                    remove_tree)


def get_path_set(locations: List[str], error_sensitive: bool = False) -> Optional[List[str]]:
	directories = list()
	for path in locations:
		for directory in expand_paths(GLOBALS.MAKE_CONFIG.get_relative_path(path)):
			if isdir(directory):
				directories.append(directory)
			else:
				if error_sensitive:
					failure(f"Declared invalid directory {path}, task will be terminated!")
					return None
				else:
					attention(f"Declared invalid directory {path}, it will be skipped.")
	return directories

def pretty_cleanup_directory(path: str) -> None:
	start_time = time.time()
	absolute_path = GLOBALS.TOOLCHAIN_CONFIG.get_path(path)
	if remove_tree(absolute_path):
		success(f"Completed {basename(path)} cleanup in {int((time.time() - start_time) * 100) / 100}s")

def collect_project_templates() -> List[str]:
	templates = []
	locations = GLOBALS.PREFERRED_CONFIG.obtain_list("projectLocations")
	for location in locations[:]:
		path = GLOBALS.TOOLCHAIN_CONFIG.get_path(location)
		if not exists(path) or not isdir(path):
			attention(f"Not found project location {location}!")
			continue
		for entry in os.listdir(path):
			template_path = join(path, entry, "template.json")
			if exists(template_path) and isfile(template_path):
				templates.append(join(location, entry))
	return templates

def request_create_project(template: Optional[str] = "../toolchain-mod") -> Optional[int]:
	have_template = "template" in GLOBALS.TOOLCHAIN_CONFIG
	always_skip_description = GLOBALS.TOOLCHAIN_CONFIG.get_value("template.skipDescription", False)
	templates = collect_project_templates()
	output_directory = None

	print("Create new project")
	from .prompt import Confirm, Feedback, Input, Review, Select

	def on_validate_template(template: str, select: Optional[Select] = None) -> bool:
		template_make_path = GLOBALS.TOOLCHAIN_CONFIG.get_path(template + "/template.json")
		try:
			template_config = FileConfig(template_make_path, raise_non_existing=True)
		except BaseException as exc:
			if select is not None:
				select.explanation = f"Malformed '{template}/template.json', nothing to do."
				return False
			if len(templates) == 0 or template == templates[0]:
				abort(f"Malformed '{template}/template.json', nothing to do.", cause=exc)
			template_config = Config()
		update_template_defaults(template_config)
		return True

	def create_template_chooser() -> Optional[Select]:
		nonlocal template
		if template and exists(GLOBALS.TOOLCHAIN_CONFIG.get_path(template)):
			on_validate_template(template)
		elif len(templates) <= 1:
			if len(templates) == 0:
				attention("You need at least one template to create a project, it can be done by creating a folder and renaming `make.json` to `template.json`.")
				abort("Not found any templates, nothing to do.")
			template = templates[0]
			on_validate_template(template)
		if len(templates) == 0 or template == templates[0]:
			return None
		template_locations = templates.copy()
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
		template=lambda _: create_template_chooser(),
		name=Input("Decide a name for your project:", on_input=update_project_name, default_text=default_name, hint="Template Project"),
		author=Input("Author who crafted this creation:", default_text=GLOBALS.TOOLCHAIN_CONFIG.get_value("template.author")),
		version=Input("What version a project starts from:", default_text=GLOBALS.TOOLCHAIN_CONFIG.get_value("template.version"), hint="1.0"),
		description=Input("Describe this masterpiece in one sentence:", default_text=GLOBALS.TOOLCHAIN_CONFIG.get_value("template.description")),
		client_side=Confirm("Is this project client-side (without server requirement)?", default_value=GLOBALS.TOOLCHAIN_CONFIG.get_value("template.clientOnly", False))
	)

	def update_template_defaults(template_config: Config) -> None:
		name = cast(Input, create_review.require_feedback("name"))
		name.hint = template_config.get_value("info.name", "Template Project")
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
		attention("Property `template.skipDescription` has disabled some options.")
	elif not have_template:
		print("You can override template by setting `template` property in your 'toolchain.json', it will be automatically apply when you create a new project. Properties remain same as `info` property in 'make.json'.", style="class:editable.hint")

	print(f"Copying template {choosen_template!r} to {output_directory!r}")
	return create_project(
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
		"packageSuffix": ensure_not_whitespace(package_suffix, "project"),
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
				attention(f"Source {dirmap[dir]!r} contains malformed name!")
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

def append_workspace_folder(folder: str, name: Optional[object] = "Project") -> None:
	if GLOBALS.CODE_WORKSPACE.available():
		folders = GLOBALS.CODE_WORKSPACE.obtain_list("folders", implace_fallback=True)
		if len(folders) == 0:
			folders.append({
				"path": GLOBALS.CODE_WORKSPACE.get_toolchain_path().replace("\\", "/"),
				"name": "Inner Core Mod Toolchain"
			})
		folders.append({
			"path": GLOBALS.CODE_WORKSPACE.get_toolchain_path(folder).replace("\\", "/"),
			"name": str(name)
		})
		GLOBALS.CODE_WORKSPACE.save_as_file()

def create_project(template: str, folder: str, name: Optional[str] = None, author: Optional[str] = None, version: Optional[str] = None, description: Optional[str] = None, clientOnly: bool = False) -> None:
	location = GLOBALS.TOOLCHAIN_CONFIG.get_relative_path(folder)
	if exists(location):
		abort(f"Folder {folder!r} already exists!")
	template_path = GLOBALS.TOOLCHAIN_CONFIG.get_path(template)
	if not exists(template_path):
		abort(f"Not found {template!r} template, nothing to do.")
	template_make_path = GLOBALS.TOOLCHAIN_CONFIG.get_path(join(template, "template.json"))
	if not isfile(template_make_path):
		abort(f"Not found 'template.json' in template {template!r}, nothing to do.")

	with open(template_make_path, "r", encoding="utf-8") as make_file:
		template_obj = json.loads(make_file.read())

	if not "info" in template_obj:
		template_obj["info"] = dict()
	template_info = template_obj["info"]
	template_info["name"] = ensure_not_whitespace(name, ensure_not_whitespace(
		template_info["name"] if "name" in template_info else None, "Project"
	))
	template_info["author"] = ensure_not_whitespace(author, ensure_not_whitespace(
		template_info["author"] if "author" in template_info else None, "ICMods"
	))
	template_info["version"] = ensure_not_whitespace(version, ensure_not_whitespace(
		template_info["version"] if "version" in template_info else None, "1.0"
	))
	template_info["description"] = description or ensure_not_whitespace(
		template_info["description"] if "description" in template_info else None, "Describe your creation just in a few words."
	)
	template_info["clientOnly"] = clientOnly if clientOnly is not None else \
		template_info["clientOnly"] if "clientOnly" in template_info else False

	os.makedirs(location, exist_ok=True)
	setup_project(template_obj, template_path, location)

	make_path = join(location, "make.json")
	with open(make_path, "w", encoding="utf-8") as make_file:
		make_file.write(json.dumps(template_obj, indent="\t", ensure_ascii=False) + "\n")

	if GLOBALS.CODE_WORKSPACE.available():
		location = GLOBALS.CODE_WORKSPACE.get_toolchain_path(folder).replace("\\", "/")
		if not any(filter(lambda folder: isinstance(folder, Config) and location == folder.get_value("path"), GLOBALS.CODE_WORKSPACE.obtain_list("folders"))):
			append_workspace_folder(folder, template_info["name"])

def resolve_mod_name(path: str, make_obj: Optional[Dict[Any, Any]] = None) -> str:
	if not make_obj:
		try:
			make_path = GLOBALS.TOOLCHAIN_CONFIG.get_path(join(path, "make.json"))
			if isfile(make_path):
				with open(make_path, "r", encoding="utf-8") as make_file:
					make_obj = json.loads(make_file.read())
		except BaseException:
			pass
	return make_obj["info"]["name"] if make_obj and "info" in make_obj and "name" in make_obj["info"] else basename(path)

def get_shortcut(path: str, make_obj: Optional[Dict[Any, Any]] = None) -> str:
	if len(path) == 0:
		return basename(GLOBALS.TOOLCHAIN_CONFIG.directory)
	return resolve_mod_name(path, make_obj) + " (" + path + ")"

def select_project(projects: List[str], prompt: Optional[str] = "Which project do you want?", prompt_when_single: Optional[str] = None, *dont_want_anymore: str) -> Optional[str]:
	if len(projects) == 1:
		itwillbe = projects[0]
		if not prompt_when_single:
			return itwillbe
		else:
			if not confirm_prompt(prompt_when_single.format(get_shortcut(itwillbe)), True):
				return None
			return itwillbe
	return select_prompt(prompt, *projects, *dont_want_anymore, selected_variant=GLOBALS.MAKE_CONFIG.current_project if GLOBALS.is_project_available() else None, returns_what=True)
