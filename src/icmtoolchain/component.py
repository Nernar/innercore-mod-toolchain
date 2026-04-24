from .context import GLOBALS
import sys
from os.path import isdir, isfile, join
from typing import Final, List, Optional

pass
from .script_setup import request_typescript
from .shell import abort, attention, frozen, pretty_print, success
from .utils import ensure_not_whitespace


class Component():
	keyword: Final[str]; name: Final[str]; location: Final[str]
	packurl: Final[Optional[str]]; commiturl: Final[Optional[str]]; branch: Final[Optional[str]]

	def __init__(self, keyword: str, name: str, location: str = "", packurl: Optional[str] = None, commiturl: Optional[str] = None, branch: Optional[str] = None):
		self.keyword = keyword
		self.name = name
		self.location = location
		if branch:
			self.packurl = "https://codeload.github.com/zheka2304/innercore-mod-toolchain/zip/" + branch
			self.commiturl = "https://raw.githubusercontent.com/zheka2304/innercore-mod-toolchain/" + branch + "/.commit"
			self.branch = branch
		if packurl:
			self.packurl = packurl
		if commiturl:
			self.commiturl = commiturl

COMPONENTS = {
	"adb": Component("adb", "Android Debug Bridge", "adb", branch="adb"),
	"declarations": Component("declarations", "TypeScript Declarations", "declarations", branch="includes"),
	"java": Component("java", "Java R8/D8 Compiler", "bin/r8", branch="r8"),
	"classpath": Component("classpath", "Java Classpath", "classpath", branch="classpath"),
	"cpp": Component("cpp", "C++ GCC Compiler (NDK)", "ndk"), # native_setup.py
	"stdincludes": Component("stdincludes", "C++ Headers", "stdincludes", branch="stdincludes")
}

def which_installed() -> List[str]:
	installed = list()
	for componentname in COMPONENTS:
		component = COMPONENTS[componentname]
		from .output_directory import get_config_directory
		path = join(get_config_directory(), component.location)
		if isdir(path):
			if component.keyword == "cpp":
				installed.append("cpp")
				continue
			if isfile(join(path, ".commit")) or GLOBALS.TOOLCHAIN_CONFIG.get_value("componentInstallationWithoutCommit", False):
				installed.append(component.keyword)
	return installed

def to_megabytes(bytes_count: int) -> str:
	return f"{(bytes_count / 1048576):.1f}MiB"

def install_components(*keywords: str) -> None:
	if len(keywords) == 0:
		return
	for keyword in keywords:
		if not keyword in COMPONENTS:
			pretty_print(f"Component {keyword!r} is not available!")
			continue
		if keyword == "cpp":
			continue
		attention(f"What do you expect? We doesn't have {COMPONENTS[keyword].packurl} anymore!")
	if "cpp" in keywords:
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
		abis = list(filter(
			lambda abi: not check_installation(abi_to_arch(abi)),
			abis
		))
		if len(abis) > 0:
			install_gcc([
				abi_to_arch(abi) for abi in abis
			], reinstall=True)

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
	pretty_print("Welcome to Inner Core Mod Toolchain! Today we will finalize setup of your own modding environment.")
	tsc_available = request_typescript(only_check=True) is not None

	preffered_components = which_installed()
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
		request_typescript()
	elif tsc_available:
		GLOBALS.TOOLCHAIN_CONFIG.set_value("denyTypeScript", True)

	GLOBALS.TOOLCHAIN_CONFIG.save_as_file()

	from .output_directory import get_script_directory
	success(f"Setup procedure is completed, Inner Core Mod Toolchain has been installed to {get_script_directory()!r} directory. Execute `icmtoolchain --help` to obtain a list of available commands. You may need to restart your console to be able to access any commands.")

def upgrade() -> int:
	from .device import download_adb
	from .java_setup import download_jdk
	from .native_setup import check_installation, install_gcc
	from .prompt import Input, Select
	from .script_setup import download_node, fetch_declarations

	while True:
		options = [
			"Node.js & TypeScript",
			"Java & JDK",
			"Android NDK & GCC",
			"Android Debug Bridge (ADB)",
			"TypeScript Declarations",
			# "C++ Headers",
			"Exit"
		]

		choice = Select("Which component should be modified?", options).request()
		if choice == 5 or choice is None:
			break

		elif choice == 0: # Node.js
			custom_node = GLOBALS.TOOLCHAIN_CONFIG.get_value("tools.node")
			status = "Custom Path: " + custom_node if custom_node else ("Installed" if isdir(join(GLOBALS.TOOLCHAIN_CONFIG.directory, "node")) else "Using System or Not Installed")
			pretty_print(f"Node.js Status: {status}")

			action = Select(variants=("Install Node.js", "Install Node.js (LTS)", "Set Custom Path", "Clear Custom Path", "Back")).request()
			if action == 0 or action == 1:
				download_node(lts=action == 1)
			elif action == 2:
				path = Input("Enter path to Node.js installation:").request()
				if path:
					GLOBALS.TOOLCHAIN_CONFIG.set_value("tools.node", path)
					GLOBALS.TOOLCHAIN_CONFIG.save_as_file()
			elif action == 3:
				GLOBALS.TOOLCHAIN_CONFIG.delete_value("tools.node")
				GLOBALS.TOOLCHAIN_CONFIG.save_as_file()

		elif choice == 1: # Java
			custom_jdk = GLOBALS.TOOLCHAIN_CONFIG.get_value("java.jdkPath")
			status = "Custom Path: " + custom_jdk if custom_jdk else ("Installed" if isdir(join(GLOBALS.TOOLCHAIN_CONFIG.directory, "java")) else "Using System or Not Installed")
			pretty_print(f"Java Status: {status}")

			action = Select(variants=("Install Temurin JDK 8", "Set Custom Path", "Clear Custom Path", "Back")).request()
			if action == 0:
				download_jdk()
			elif action == 1:
				path = Input("Enter path to JDK installation:").request()
				if path:
					GLOBALS.TOOLCHAIN_CONFIG.set_value("java.jdkPath", path)
					GLOBALS.TOOLCHAIN_CONFIG.save_as_file()
			elif action == 2:
				GLOBALS.TOOLCHAIN_CONFIG.delete_value("java.jdkPath")
				GLOBALS.TOOLCHAIN_CONFIG.save_as_file()

		elif choice == 2: # NDK
			custom_ndk = GLOBALS.TOOLCHAIN_CONFIG.get_value("native.ndkPath", GLOBALS.TOOLCHAIN_CONFIG.get_value("ndkPath"))
			installed_arm = check_installation(["arm", "arm64"])
			status = "Custom Path: " + custom_ndk if custom_ndk else ("Installed" if installed_arm else "Not Installed")
			pretty_print(f"NDK Status: {status}")

			action = Select(variants=("Install NDK (arm/arm64)", "Set Custom Path", "Clear Custom Path", "Back")).request()
			if action == 0:
				install_gcc(["arm", "arm64"], reinstall=True)
			elif action == 1:
				path = Input("Enter path to NDK installation:").request()
				if path:
					GLOBALS.TOOLCHAIN_CONFIG.set_value("native.ndkPath", path)
					GLOBALS.TOOLCHAIN_CONFIG.save_as_file()
			elif action == 2:
				GLOBALS.TOOLCHAIN_CONFIG.delete_value("native.ndkPath")
				GLOBALS.TOOLCHAIN_CONFIG.save_as_file()

		elif choice == 3: # ADB
			custom_adb = GLOBALS.TOOLCHAIN_CONFIG.get_value("adb.path")
			status = "Custom Path: " + custom_adb if custom_adb else ("Installed" if isdir(join(GLOBALS.TOOLCHAIN_CONFIG.directory, "adb")) else "Using System or Not Installed")
			pretty_print(f"ADB Status: {status}")

			action = Select(variants=("Install ADB", "Set Custom Path", "Clear Custom Path", "Back")).request()
			if action == 0:
				download_adb()
			elif action == 1:
				path = Input("Enter path to ADB executable:").request()
				if path:
					GLOBALS.TOOLCHAIN_CONFIG.set_value("adb.path", path)
					GLOBALS.TOOLCHAIN_CONFIG.save_as_file()
			elif action == 2:
				GLOBALS.TOOLCHAIN_CONFIG.delete_value("adb.path")
				GLOBALS.TOOLCHAIN_CONFIG.save_as_file()

		elif choice == 4: # Declarations
			decl_dir = join(GLOBALS.TOOLCHAIN_CONFIG.directory, "declarations")
			status = "Installed" if isdir(decl_dir) else "Not Installed"
			pretty_print(f"Declarations Status: {status}")

			action = Select(variants=("Fetch Declarations", "Back")).request()
			if action == 0:
				fetch_declarations()

	return 0


if __name__ == "__main__":
	if "--help" in sys.argv:
		pretty_print("Usage: python component.py [options] <components>")
		pretty_print(" " * 2 + "--startup: Initial settings instead of a component updates.")
		exit(0)
	if "--startup" in sys.argv or "-s" in sys.argv:
		startup()
	else:
		upgrade()
