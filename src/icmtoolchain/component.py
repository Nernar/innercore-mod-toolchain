import sys
from os.path import isdir, isfile, join
from typing import Any, Callable, Final, List, Optional, Tuple

from .context import GLOBALS
from .errors import abort
from .logger import attention, frozen, print, success
from .output_directory import get_config_directory
from .prompt import Input, Select
from .utils import ensure_not_whitespace, remove_tree


class Component():
	keyword: Final[str]; name: Final[str]; location: Final[str]
	config_key: Final[Optional[str]]; legacy_keys: Final[List[str]]
	installable: Final[bool]; on_install: Final[Optional[Callable]]
	packurl: Final[Optional[str]]; commiturl: Final[Optional[str]]; branch: Final[Optional[str]]

	def __init__(self, keyword: str, name: str, location: str = "", config_key: Optional[str] = None, legacy_keys: Optional[List[str]] = None, installable: bool = True, on_install: Optional[Callable] = None, branch: Optional[str] = None):
		self.keyword = keyword
		self.name = name
		self.location = location
		self.config_key = config_key
		self.legacy_keys = legacy_keys or []
		self.installable = installable
		self.on_install = on_install
		if branch:
			self.packurl = "https://codeload.github.com/zheka2304/innercore-mod-toolchain/zip/" + branch
			self.commiturl = "https://raw.githubusercontent.com/zheka2304/innercore-mod-toolchain/" + branch + "/.commit"
			self.branch = branch

def install_node(**kwargs) -> None:
	from .script_setup import download_node
	download_node(lts=kwargs.get("lts", False))

def install_java(**kwargs) -> None:
	from .java_setup import download_jdk
	download_jdk()

def install_cpp(**kwargs) -> None:
	abis = GLOBALS.TOOLCHAIN_CONFIG.obtain_list("native.abis")
	if len(abis) == 0:
		abis = GLOBALS.TOOLCHAIN_CONFIG.obtain_list("abis")
	abi = GLOBALS.TOOLCHAIN_CONFIG.get_value("native.debugAbi")
	if not abi:
		abi = GLOBALS.TOOLCHAIN_CONFIG.get_value("debugAbi")
	if not abi and len(abis) == 0:
		abort("Please describe options `abis` or `debugAbi` in your 'toolchain.json' before installing NDK!")
	if abi and not abi in abis:
		abis.append(abi)
	from .native_setup import abi_to_arch, check_installation, install_gcc
	if not kwargs.get("reinstall", False):
		abis = list(filter(lambda abi: not check_installation(abi_to_arch(abi)), abis))
	if len(abis) > 0:
		install_gcc([abi_to_arch(abi) for abi in abis], reinstall=True)

def install_adb(**kwargs) -> None:
	from .adb import download_adb
	download_adb()

def install_declarations(**kwargs) -> None:
	from .script_setup import fetch_declarations
	fetch_declarations()


COMPONENTS = {
	"node": Component("node", "Node.js & TypeScript", "node", config_key="tools.node", on_install=install_node),
	"adb": Component("adb", "Android Debug Bridge", "adb", config_key="tools.adb", legacy_keys=["adb.path"], branch="adb", on_install=install_adb),
	"declarations": Component("declarations", "TypeScript Declarations", "declarations", branch="includes", on_install=install_declarations),
	"java": Component("java", "Java R8/D8 Compiler", "bin/r8", config_key="tools.jdk", legacy_keys=["java.jdkPath"], branch="r8", on_install=install_java),
	"classpath": Component("classpath", "Java Classpath", "classpath", branch="classpath"),
	"cpp": Component("cpp", "C++ GCC Compiler (NDK)", "ndk", config_key="tools.ndk", legacy_keys=["native.ndkPath", "ndkPath"], on_install=install_cpp),
	"stdincludes": Component("stdincludes", "C++ Headers", "stdincludes", installable=False, branch="stdincludes")
}

def is_installed(component: Component) -> bool:
	from .output_directory import get_config_directory
	if component.keyword == "java":
		return isdir(join(get_config_directory(), "java"))
	if component.keyword == "cpp":
		from .native_setup import check_installation
		return check_installation(["arm", "arm64"])
	
	path = join(get_config_directory(), component.location)
	if isdir(path):
		if component.keyword in ("node", "adb") or not component.on_install:
			return True
		return isfile(join(path, ".commit")) or GLOBALS.TOOLCHAIN_CONFIG.get_value("componentInstallationWithoutCommit", False)
	return False

def get_custom_path(component: Component) -> Optional[str]:
	if not component.config_key:
		return None
	path = GLOBALS.TOOLCHAIN_CONFIG.get_value(component.config_key)
	if path is not None:
		return path
	for legacy_key in component.legacy_keys:
		path = GLOBALS.TOOLCHAIN_CONFIG.get_value(legacy_key)
		if path is not None:
			return path
	return None

def get_pretty_component_status(custom_path: Optional[str], installed: bool) -> list:
	if custom_path:
		return [("class:print.frozen", " (Custom)")]
	if installed:
		return [("class:print.success", " (Installed)")]
	return []

def build_component_menu_options() -> Tuple[List[Any], List[str]]:
	options = []
	keys = []
	for key, component in COMPONENTS.items():
		custom_path = get_custom_path(component)
		installed = is_installed(component)
		options.append([("", component.name)] + get_pretty_component_status(custom_path, installed))
		keys.append(key)
	return options, keys

def to_megabytes(bytes_count: int) -> str:
	return f"{(bytes_count / 1048576):.1f}MiB"

def install_components(*keywords: str, **kwargs: Any) -> None:
	if len(keywords) == 0:
		return
	for keyword in keywords:
		if not keyword in COMPONENTS:
			print(f"Component {keyword!r} is not available!")
			continue

		component = COMPONENTS[keyword]
		if component.on_install:
			component.on_install(**kwargs)
		elif not is_installed(component):
			from .output_directory import get_config_directory
			extract_path = join(get_config_directory(), component.location)
			if component.packurl:
				attention(f"{component.name} cannot be installed automatically. Please download it manually from {component.packurl} and extract to {extract_path!r}.")
			else:
				attention(f"{component.name} cannot be installed automatically. Please install it manually into {extract_path!r}.")

def get_username() -> Optional[str]:
	username = GLOBALS.TOOLCHAIN_CONFIG.get_value("template.author")
	if username:
		return username
	try:
		from getpass import getuser
		return ensure_not_whitespace(getuser())
	except ImportError:
		return None

def startup() -> None:
	from .script_setup import request_typescript
	tsc_available = request_typescript(only_check=True) is not None

	preffered_components = list()
	for key, component in COMPONENTS.items():
		if is_installed(component):
			preffered_components.append(key)
	if not "declarations" in preffered_components:
		preffered_components.append("declarations")
	try:
		import shutil
		if shutil.which("adb") is None and not "adb" in preffered_components:
			preffered_components.append("adb")
	except BaseException:
		pass

	component_keys = []
	component_variants = []
	for key in COMPONENTS:
		name = COMPONENTS[key].name
		if key in preffered_components:
			preffered_components.remove(key)
			preffered_components.append(name)
		component_keys.append(key)
		component_variants.append(name)

	from .prompt import Checkbox, Confirm, Input, Review
	print("Welcome to Inner Core Mod Toolchain! Today we will finalize setup of your own modding environment.")
	welcome_review = Review(
		username=Input("Who are you?", hint=get_username(), use_hint_as_fallback=False, explanation="This username, or alias, will be used when creating a project. Author name identifies you on Inner Core Mods."),
		components=Checkbox("What will be used for development?", variants=component_variants, selected_variants=preffered_components, allow_to_choose_nothing=True, explanation="If you don't know what you need, toolchain will offer to install component when necessary."),
		use_typescript=Confirm("Do you plan to use Node.js for compilation?", default_value=tsc_available, explanation="This will allow your code to be transpiled by TypeScript Compiler to use ESNext's features, but may increase reassembly time."),
		import_location=Input("Where should we look for projects?", explanation="If you have used Inner Core Mod Toolchain earlier, you may choose where to search for projects. Either import an obsolete project or modification for Inner Core.")
	)

	try:
		results = welcome_review.request(returns_empty_properties=True)
	except (KeyboardInterrupt, EOFError):
		frozen("Preconfiguration was canceled, you can do it later, execute `icmtoolchain --help` for a list of commands.")
		return None

	username = ensure_not_whitespace(results["username"])
	if username:
		GLOBALS.TOOLCHAIN_CONFIG.set_value("template.author", username)

	components = results["components"]
	if components and len(components) > 0:
		install_components(*[component_keys[index] for index in components])

	use_typescript = results["use_typescript"]
	if use_typescript:
		if GLOBALS.TOOLCHAIN_CONFIG.get_value("denyTypeScript"):
			GLOBALS.TOOLCHAIN_CONFIG.delete_value("denyTypeScript")
		from .script_setup import request_typescript
		request_typescript()
	elif tsc_available:
		GLOBALS.TOOLCHAIN_CONFIG.set_value("denyTypeScript", True)

	GLOBALS.TOOLCHAIN_CONFIG.save_as_file()

	success("Inner Core Mod Toolchain has been installed!")
	print(f"Configurations are stored in {get_config_directory()!r}.")
	print("Execute `icmtoolchain --help` to obtain a list of available commands.")
	attention("You may need to restart your console to be able to access any commands.")

def upgrade() -> None:
	while True:
		try:
			options, keys = build_component_menu_options()
			options.append("Exit")

			choice = Select("Which component should be configured?", options).request()
			if choice is None or choice == len(options) - 1:
				break

			selected_key = keys[choice]
			component = COMPONENTS[selected_key]
			
			custom_path = get_custom_path(component)
			installed = is_installed(component)
			remove_dir = join(get_config_directory(), "java" if selected_key == "java" else component.location)

			submenu_prompt = f"How {component.name} will be changed?"

			explanation = None
			if custom_path:
				explanation = f"Custom Path: {custom_path}"
			elif installed:
				explanation = f"Path: {remove_dir}"

			update_available = False # TODO

			actions = []
			if update_available:
				actions.append("Update")
			if component.installable:
				actions.append(f"{'Reinstall' if installed else 'Install'}")
				if selected_key == "node":
					actions.append(f"{'Reinstall' if installed else 'Install'} (LTS)")
			if component.config_key:
				actions.append("Set Custom Path")
				if custom_path:
					actions.append("Unset Custom Path")
			if installed:
				actions.append("Uninstall")
			actions.append("Go Back")

			action_str = Select(submenu_prompt, variants=actions, explanation=explanation, returns_what=True).request()
			if action_str is None or action_str == "Go Back":
				continue

			if "Install" in action_str or "Reinstall" in action_str or action_str == "Update":
				lts = "(LTS)" in action_str
				reinstall = "Reinstall" in action_str or action_str == "Update"
				install_components(selected_key, lts=lts, reinstall=reinstall)

				if component.config_key and custom_path:
					GLOBALS.TOOLCHAIN_CONFIG.delete_value(component.config_key)
					for k in component.legacy_keys:
						GLOBALS.TOOLCHAIN_CONFIG.delete_value(k)
					GLOBALS.TOOLCHAIN_CONFIG.save_as_file()

			elif action_str == "Set Custom Path":
				assert component.config_key
				path = Input(f"Enter path to {component.name}:").request()
				if path:
					GLOBALS.TOOLCHAIN_CONFIG.set_value(component.config_key, path)
					GLOBALS.TOOLCHAIN_CONFIG.save_as_file()

			elif action_str == "Unset Custom Path":
				assert component.config_key
				GLOBALS.TOOLCHAIN_CONFIG.delete_value(component.config_key)
				for k in component.legacy_keys:
					GLOBALS.TOOLCHAIN_CONFIG.delete_value(k)
				GLOBALS.TOOLCHAIN_CONFIG.save_as_file()

			elif action_str == "Uninstall":
				remove_tree(remove_dir)
				success(f"{component.name} was uninstalled.")
		except KeyboardInterrupt:
			break


if __name__ == "__main__":
	if "--help" in sys.argv:
		print("Usage: python component.py [options] <components>")
		print(" " * 2 + "--startup: Initial settings instead of a component updates.")
		exit(0)
	if "--startup" in sys.argv or "-s" in sys.argv:
		startup()
	else:
		upgrade()
