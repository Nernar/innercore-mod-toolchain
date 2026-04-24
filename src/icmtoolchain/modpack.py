from .context import GLOBALS
from os.path import basename, join
from typing import List, Optional

from .shell import abort, pretty_print, select_prompt, pretty_error, attention
from .adb import test_directory_exist, ls


def get_modpack_push_directory() -> Optional[str]:
	directory = GLOBALS.PREFERRED_CONFIG.get_value("pushTo", allow_prototype=False)
	if not directory:
		directory = GLOBALS.TOOLCHAIN_CONFIG.get_value("pushTo")
		if directory:
			if not GLOBALS.is_project_available() or not GLOBALS.MAKE_CONFIG.current_project:
				return None
			directory = join(directory, "mods", basename(GLOBALS.MAKE_CONFIG.current_project)) if "/packs/" in directory \
				else join(directory, basename(GLOBALS.MAKE_CONFIG.current_project))

	if not directory:
		GLOBALS.TOOLCHAIN_CONFIG.set_value("pushTo", setup_modpack_directory())
		if not GLOBALS.PREFERRED_CONFIG.get_value("pushTo"):
			abort("Not found any modpacks, nothing to do.")
		GLOBALS.TOOLCHAIN_CONFIG.save_as_file()
		return get_modpack_push_directory()

	if "horizon" not in directory and "innercore" not in directory and not GLOBALS.PREFERRED_CONFIG.get_value("adb.pushAnyLocation", False):
		pretty_print(
			f"Push directory {directory!r} looks suspicious, it does not belong to Horizon packs directory. " +
			"This action may easily corrupt all content inside, allow only if you know what are you doing."
		)
		which = select_prompt(
			"What will you do?",
			"Choice another modpack",
			"Push it anyway",
			"No questions, always push",
			"Nothing",
			fallback=3,
			prints_abort=False
		)

		if which == 0:
			GLOBALS.TOOLCHAIN_CONFIG.delete_value("pushTo")
			if GLOBALS.TOOLCHAIN_CONFIG != GLOBALS.PREFERRED_CONFIG:
				GLOBALS.PREFERRED_CONFIG.delete_value("pushTo")
			return get_modpack_push_directory()
		elif which == 2:
			GLOBALS.TOOLCHAIN_CONFIG.set_value("adb.pushAnyLocation", True)
			GLOBALS.TOOLCHAIN_CONFIG.save_as_file()
			pretty_print("This may be changed in your 'toolchain.json' config.")
		elif which == 3:
			attention("Pushing aborted.")
			return None

	return directory

def ls_packs_on_remote(path: str) -> List[str]:
	directories = []
	if test_directory_exist(path + "/innercore/mods"):
		directories.append(path + "/innercore")
	return directories + [path + "/modpacks/" + directory for directory in ls(path + "/modpacks")[0] \
		if test_directory_exist(path + "/modpacks/" + directory + "/mods")]

def person_readable_modpack_name(path: str) -> str:
	what = path.split("/")[::-1]
	try:
		suffix = " (internal)" if "Android/data" in path else ""
		if what[0] == "com.mojang":
			return "Legacy Core Engine" + suffix
		if what[0] == "innercore":
			return what[1] + suffix
		if what[3] == "packs":
			return f"{basename(path)} in {what[2]}" + suffix
		return "/".join(what[0:2][::-1]) + suffix
	except IndexError:
		pass
	return basename(path)

def get_sdcard_directory() -> Optional[str]:
	locations = GLOBALS.TOOLCHAIN_CONFIG.get_value("storageLocations")
	if not locations or len(locations) == 0:
		locations = ["/sdcard", "/storage/emulated/0", "/mnt/sdcard"]
	for location in locations:
		if test_directory_exist(location):
			return location
	if test_directory_exist("/storage/emulated"):
		directories = ls("/storage/emulated")[0]
		for directory in directories:
			if test_directory_exist("/storage/emulated/" + directory):
				return "/storage/emulated/" + directory
	return None

def setup_modpack_directory() -> Optional[str]:
	locations = GLOBALS.TOOLCHAIN_CONFIG.get_value("modpackLocations")
	if not locations or len(locations) == 0:
		locations = [
			"games/horizon/packs",
			"Android/media/com.zheka.horizon64/packs",
			"Android/media/com.zheka.horizon/packs",
			"Android/media/com.zheka.horizon32/packs",
			"Android/data/com.zheka.horizon64/files/packs",
			"Android/data/com.zheka.horizon64/files/horizon/packs",
			"Android/data/com.zheka.horizon/files/packs",
			"Android/data/com.zheka.horizon/files/horizon/packs",
			"Android/data/com.zheka.horizon32/files/packs",
			"Android/data/com.zheka.horizon32/files/horizon/packs",
		]
	sdcard_directory = get_sdcard_directory()
	if not sdcard_directory:
		pretty_error("We were unable to find storage folder on your device.")
		pretty_error("Please override `storageLocations` property in your 'toolchain.json' to override path.")
		return None
	directories = set()
	for location in locations:
		modpack_directory = sdcard_directory + "/" + location
		directories.update(ls_packs_on_remote(modpack_directory))
		for relative_directory in ls(modpack_directory)[0]:
			directories.update(ls_packs_on_remote(modpack_directory + "/" + relative_directory))
	if test_directory_exist(sdcard_directory + "/games/com.mojang/mods"):
		directories.add(sdcard_directory + "/games/com.mojang")
	if len(directories) == 0:
		pretty_error("It looks like your device does not contain an Inner Core installation.")
		pretty_error("Please install pack via Horizon or override `modpackLocations` property of your 'toolchain.json'.")
		return None
	directories_list = list(directories)
	readable_directories = [person_readable_modpack_name(directory) for directory in directories_list]
	which = select_prompt("Which modpack will be used?", *readable_directories)
	return None if which is None else directories_list[which]
