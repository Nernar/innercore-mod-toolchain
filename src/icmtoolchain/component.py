import os
import sys
from os.path import isdir, isfile, join
from typing import Final, List, Optional

from . import GLOBALS
from .shell import abort, pretty_print
from .utils import ensure_not_whitespace, request_typescript


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
		path = GLOBALS.TOOLCHAIN_CONFIG.get_path(component.location)
		if not isdir(path):
			continue
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
			pretty_print(f"Component {keyword!r} not available!")
			continue
		if keyword == "cpp":
			continue
		# component = COMPONENTS[keyword]
		# progress = Progress(text=component.name)
	if "cpp" in keywords:
		abis = GLOBALS.TOOLCHAIN_CONFIG.get_list("native.abis")
		if len(abis) == 0:
			abis = GLOBALS.TOOLCHAIN_CONFIG.get_list("abis")
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

def get_script_directory() -> str:
    script_directory = None
    try:
        script_path = os.path.realpath(__file__)
        script_directory = os.path.dirname(script_path)
        return script_directory
    except (AttributeError, NameError):
        pass
    try:
        if not sys.argv or not sys.argv[0]:
            raise ValueError("sys.argv[0] is empty")
        script_path = os.path.realpath(sys.argv[0])
        if os.path.isfile(script_path):
            return os.path.dirname(script_path)
        return script_path
    except (IndexError, ValueError, OSError):
        pass
    return os.getcwd()

def startup() -> None:
	pretty_print("Welcome to Inner Core Mod Toolchain! Today we will finalize setup of your own modding environment.")
	tsc_available = request_typescript(only_check=True) is not None
	from .prompt import Confirm, Input, Review
	welcome_review = Review(
		username=Input("Who are you?", hint=get_username(), use_hint_as_fallback=False, explanation="This username, or alias, will be used when creating a project. Author name identifies you on Inner Core Mods."),
		use_typescript=Confirm("Do you plan to use Node.js for compilation?", default_value=tsc_available, explanation="This will allow your code to be transpiled by TypeScript Compiler to use ESNext's features, but may increase reassembly time."),
		import_location=Input("Where should we look for projects?", explanation="If you have used Inner Core Mod Toolchain earlier, you may choose where to search for projects. Either import an obsolete project or modification for Inner Core.")
	)

	# TODO: Reuse someday...
	preffered_components = which_installed()
	if not "declarations" in preffered_components:
		preffered_components.append("declarations")
	try:
		import shutil
		if shutil.which("adb") is None and not "adb" in preffered_components:
			preffered_components.append("adb")
	except BaseException:
		pass

	try:
		results = welcome_review.request(returns_empty_properties=True)
	except KeyboardInterrupt or EOFError:
		pretty_print("* Preconfiguration was canceled, you can do it later, execute `icmtoolchain --help` for a list of commands.")
		return None

	username = ensure_not_whitespace(results["username"])
	if username:
		GLOBALS.TOOLCHAIN_CONFIG.set_value("template.author", username)

	use_typescript = results["use_typescript"]
	if use_typescript:
		if GLOBALS.TOOLCHAIN_CONFIG.get_value("denyTypeScript"):
			GLOBALS.TOOLCHAIN_CONFIG.remove_value("denyTypeScript")
		request_typescript()
	elif tsc_available:
		GLOBALS.TOOLCHAIN_CONFIG.set_value("denyTypeScript", True)

	GLOBALS.TOOLCHAIN_CONFIG.save()

	pretty_print(f"* Setup procedure is completed, Inner Core Mod Toolchain has been installed to {get_script_directory()!r} directory. Execute `icmtoolchain --help` to obtain a list of available commands. You may need to restart your console to be able to access any commands.")

def upgrade() -> int:
	pretty_print("Nothing to perform.")
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
