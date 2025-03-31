import colorama
import sys
from os.path import isdir, isfile, join
from typing import Final, List, Optional

from . import GLOBALS
from .shell import (PLATFORM_STYLE_DIM, Input, InteractiveShell, Interrupt,
                    Notice, Progress, SelectiveShell, Separator, Shell, Switch,
                    abort, stringify)
from .utils import (ensure_not_whitespace, request_typescript)


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

def resolve_selected_components(interactables: List[Shell.Interactable]) -> List[str]:
	keywords = list()
	for interactable in interactables:
		if isinstance(interactable, Switch) and interactable.key and interactable.key.startswith("component:") and interactable.checked:
			keywords.append(interactable.key.partition(":")[2])
	return keywords

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
	shell = InteractiveShell(lines_per_page=max(len(keywords), 9))
	with shell:
		for keyword in keywords:
			if not keyword in COMPONENTS:
				print(f"Component {keyword!r} not availabled!")
				continue
			if keyword == "cpp":
				continue
			component = COMPONENTS[keyword]
			progress = Progress(text=component.name)
			shell.interactables.append(progress)
			shell.render()
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
		shell.interactables.append(Interrupt())

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
	print("Welcome to Inner Core Mod Toolchain!", end="")
	shell = SelectiveShell()
	shell.interactables += [
		Separator(),
		Notice("Today, we will complete setup of your own modding"),
		Notice("environment; use enter and arrow keys on computer"),
		Notice("keyboard to interact with console interface."),
		Separator(),
		Progress(progress=0.2, text="  " + "Howdy!".center(43) + "->")
	]
	shell.interactables += [
		Separator(),
		Input("user", "I will be ", template=get_username()),
		Notice("Username is used as primary `author` attribute when"),
		Notice("creating a project, it identifies you in mod browser."),
		Separator(),
		Progress(progress=0.4, text="<-" + "Who are you?".center(43) + "->")
	]

	preffered = which_installed()
	if not "declarations" in preffered:
		preffered.append("declarations")
	try:
		import shutil
		if shutil.which("adb") is None and not "adb" in preffered:
			preffered.append("adb")
	except BaseException:
		pass

	components = [
		Switch("component:" + key, COMPONENTS[key].name, True if key in preffered else False) for key in COMPONENTS
	]
	interactables: List[Shell.Interactable] = [
		Notice("Which components need to be installed?")
	]
	component = 0
	index = len(interactables)

	while True:
		if index % shell.lines_per_page == shell.lines_per_page - 1:
			interactables.append(Progress(progress=0.6, text="<-" + "Configure your toolchain".center(43) + "->"))
			if component == len(components) + 3:
				break
		elif component < len(components) + 3:
			if component < len(components):
				interactables.append(components[component])
			elif component == len(components):
				interactables.append(Separator())
			elif component == len(components) + 1:
				interactables.append(Notice("Any component can be installed or updated later, and it is"))
			elif component == len(components) + 2:
				interactables.append(Notice("not necessary to install what you do not currently need."))
			component += 1
		else:
			required_lines = shell.lines_per_page - ((index + 1) % shell.lines_per_page)
			interactables.append(Separator(size=required_lines))
			index += required_lines - 1
		index += 1
	shell.interactables.extend(interactables)

	tsc = request_typescript(only_check=True) is not None
	shell.interactables += [
		Separator(),
		Switch("typescript", "Do you want to use Node.js for script compilation?", tsc),
		Notice("This will allow you to use TypeScript and modern ESNext"),
		Notice("features, but it may slow down build speed."),
		Separator(),
		Progress(progress=0.8, text="<-" + "Composite performance".center(43) + "  ")
	]
	shell.interactables.append(Interrupt())
	try:
		shell.loop()
	except KeyboardInterrupt:
		shell.leave()
		print()
		print("* You have exited installation process, settings will not be saved. Environment is available in folder specified in console.")
		return
	print()

	username = ensure_not_whitespace(shell.get_interactable("user", Input).read())
	if username:
		print("What name will be used for publishing mods?", stringify(username, color=PLATFORM_STYLE_DIM, reset=colorama.Style.RESET_ALL))
		GLOBALS.TOOLCHAIN_CONFIG.set_value("template.author", username)

	typescript = shell.get_interactable("typescript", Switch).checked
	print("Will all scripts be compiled using Node.js?", stringify("yes" if typescript else "no", color=PLATFORM_STYLE_DIM, reset=colorama.Style.RESET_ALL))
	if typescript:
		if GLOBALS.TOOLCHAIN_CONFIG.get_value("denyTypeScript"):
			GLOBALS.TOOLCHAIN_CONFIG.remove_value("denyTypeScript")
			GLOBALS.TOOLCHAIN_CONFIG.save()
		request_typescript()
	elif tsc:
		GLOBALS.TOOLCHAIN_CONFIG.set_value("denyTypeScript", True)
		GLOBALS.TOOLCHAIN_CONFIG.save()

	GLOBALS.TOOLCHAIN_CONFIG.save()

	pending = resolve_selected_components(shell.interactables)
	if len(pending) > 0:
		print("Which components need to be installed?", stringify(", ".join(pending), color=PLATFORM_STYLE_DIM, reset=colorama.Style.RESET_ALL))
		install_components(*pending)

	print("* Installation process is completed! You can now use environment as usual; simply open `toolchain.code-workspace` file or toolchain folder through your favorite IDE.")

def upgrade() -> int:
	print("Which components need to be updated?", end="")
	shell = SelectiveShell(lines_per_page=min(len(COMPONENTS), 9))
	shell.interactables += [
		Switch("component:" + key, COMPONENTS[key].name, True if key in which_installed() else False) for key in COMPONENTS
	]
	shell.interactables.append(Interrupt())
	try:
		shell.loop()
	except KeyboardInterrupt:
		print(); return 1
	installed = resolve_selected_components(shell.interactables)
	if len(installed) > 0:
		print("Which components need to be updated?", stringify(", ".join(installed), color=PLATFORM_STYLE_DIM, reset=colorama.Style.RESET_ALL))
		install_components(*installed)
	else:
		print()
		print("Nothing to perform.")
	return 0


if __name__ == "__main__":
	if "--help" in sys.argv:
		print("Usage: python component.py [options] <components>")
		print(" " * 2 + "--startup: Initial settings instead of a component updates.")
		exit(0)
	if "--startup" in sys.argv or "-s" in sys.argv:
		startup()
	else:
		upgrade()
