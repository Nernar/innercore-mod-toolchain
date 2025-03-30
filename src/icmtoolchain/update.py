from os.path import isfile

from . import GLOBALS
from .shell import warn

def update_toolchain() -> None:
	commit_path = GLOBALS.TOOLCHAIN_CONFIG.get_path("bin/.commit")
	commit = None
	if isfile(commit_path):
		with open(commit_path) as file:
			commit = file.read().strip()
	if not isfile(commit_path):
		warn("Successfully installed, but corresponding 'bin/.commit' not found, further update will be installed without any prompt.")
	else:
		with open(commit_path) as file:
			branch_commit = file.read().strip()
		if commit:
			print(f"Successfully installed {branch_commit[:7]} above {commit[:7]} revision!")
		else:
			print(f"Successfully installed under {branch_commit[:7]} revision!")
