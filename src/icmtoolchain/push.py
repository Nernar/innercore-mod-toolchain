from .context import GLOBALS
import subprocess
from os.path import basename, isdir, isfile, join, relpath
from typing import List, Optional

from .hglob import glob
from .shell import InteractiveSession, Progress
from .logger import print, error, failure, success
from .errors import abort
from .utils import DEVNULL
from .modpack import get_modpack_push_directory


def push_everything(push_unchanged: bool = True, cleanup_remote: bool = True) -> int:
	destination_directory = get_modpack_push_directory()
	if not destination_directory:
		# probably someday it will return 0, but only when we merge push and launch
		return 1

	push_unchanged = GLOBALS.PREFERRED_CONFIG.get_value("adb.pushUnchangedFiles", push_unchanged)
	cleanup_remote = GLOBALS.PREFERRED_CONFIG.get_value("adb.cleanupRemote", cleanup_remote)

	result = push_directory(GLOBALS.PROJECT_STRUCTURE.directory, destination_directory, push_unchanged=push_unchanged, cleanup_remote=cleanup_remote)
	if result > 0:
		return result
	for linked_resource in GLOBALS.LINKED_RESOURCE_STORAGE.iterate_resources():
		project_path = GLOBALS.MAKE_CONFIG.get_relative_path(linked_resource["relative_path"])
		remote_path = destination_directory + "/" + linked_resource["output_path"]
		remote_push_unchanged = linked_resource["push_unchanged"] if "push_unchanged" in linked_resource else push_unchanged
		remote_cleanup_remote = linked_resource["cleanup_remote"] if "cleanup_remote" in linked_resource else cleanup_remote
		if isfile(project_path):
			result = push_file(project_path, remote_path, push_unchanged=remote_push_unchanged, cleanup_remote=remote_cleanup_remote) or result
		elif isdir(project_path):
			result = push_directory(project_path, remote_path, push_unchanged=remote_push_unchanged, cleanup_remote=remote_cleanup_remote) or result
		else:
			print()
			abort(f"We cannot push {linked_resource['relative_path']!r} resource because we could not determine its type!")
		if result > 0:
			return result
	if result < 0:
		success("All files already up to date.")

	GLOBALS.OUTPUT_STORAGE.save()
	return 0

def push_file(file: str, destination_file: str, push_unchanged: bool = True, cleanup_remote: bool = True) -> int:
	if not push_unchanged and not GLOBALS.OUTPUT_STORAGE.is_path_changed(file):
		return -1

	readable_name = basename(file)
	with InteractiveSession(progress=Progress(f"Pushing file {readable_name}")) as session:
		destination_file = destination_file.replace("\\", "/")
		if not destination_file.startswith("/"):
			destination_file = "/" + destination_file
		sources_file = file.replace("\\", "/")
		# try:
		if cleanup_remote:
			subprocess.call(GLOBALS.ADB_COMMAND + [
				"shell", "rm", "-r", destination_file
			], stderr=DEVNULL, stdout=DEVNULL)
		result = subprocess.run(GLOBALS.ADB_COMMAND + [
			"push", sources_file, destination_file
		], capture_output=True, text=True)
		# XXX: except KeyboardInterrupt:
			# Progress.notify(shell, progress, 1, "Pushing aborted.")
			# return 1

		if result.returncode != 0:
			cause = (result.stderr.strip() or result.stdout.strip()).splitlines()
			if cause and len(cause[-1]) > 0:
				error(cause[-1])
			failure(f"Failed to push file {readable_name!r} with error code {result.returncode}!")
			return result.returncode

	success(f"Pushed file {readable_name!r} into {destination_file!r}.")
	return result.returncode

def push_directory(directory: str, destination_directory: str, push_unchanged: bool = True, cleanup_remote: bool = True) -> int:
	items = [
		relpath(path, directory) for path in glob(directory + "/*") \
			if push_unchanged or GLOBALS.OUTPUT_STORAGE.is_path_changed(path)
	]
	files_count = len(items)
	if files_count == 0:
		return -1

	readable_name = basename(directory)
	with InteractiveSession(progress=Progress(f"Pushing {readable_name}/")) as session:
		destination_directory = destination_directory.replace("\\", "/")
		if not destination_directory.startswith("/"):
			destination_directory = "/" + destination_directory
		sources_directory = directory.replace("\\", "/")

		offset = 0
		for filename in items:
			src = sources_directory + "/" + filename
			dst = destination_directory + "/" + filename
			session["progress"].update(offset / files_count, f"Pushing {readable_name}/{filename}")
			# try:
			if cleanup_remote:
				subprocess.call(GLOBALS.ADB_COMMAND + [
					"shell", "rm", "-r", dst
				], stderr=DEVNULL, stdout=DEVNULL)
			result = subprocess.run(GLOBALS.ADB_COMMAND + [
				"push", src, dst
			], capture_output=True, text=True)
			# XXX: except KeyboardInterrupt:
				# Progress.notify(shell, progress, 1, "Pushing aborted.")
				# return 1
			offset += 1

			if result.returncode != 0:
				cause = (result.stderr.strip() or result.stdout.strip()).splitlines()
				if cause and len(cause[-1]) > 0:
					error(cause[-1])
				failure(f"Failed to push directory {readable_name!r} with error code {result.returncode}!")
				return result.returncode

	success(f"Pushed directory {readable_name!r} into {destination_directory!r}.")
	return 0

def make_locks(*locks: str) -> int:
	destination_directory = get_modpack_push_directory()
	if not destination_directory:
		return -1

	for lock in locks:
		lock = join(destination_directory, lock).replace("\\", "/")
		result = subprocess.call(GLOBALS.ADB_COMMAND + [
			"shell", "touch", lock
		])
		if result != 0:
			return result
	return 0
