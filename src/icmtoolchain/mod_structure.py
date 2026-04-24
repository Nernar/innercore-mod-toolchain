import json
from os.path import basename, isfile
from typing import Any, Dict, List

from .logger import attention
from .utils import ensure_file


class LinkedResourceStorage:
	contents: List[Dict]
	latest_contents: List[Dict]
	contents_path: str

	def __init__(self, contents_path: str) -> None:
		self.contents = list()
		self.contents_path = contents_path
		self.read_contents()

	def read_contents(self):
		if not isfile(self.contents_path):
			return
		with open(self.contents_path, encoding="utf-8") as contents_file:
			try:
				contents = json.load(contents_file)
				if isinstance(contents, list):
					self.latest_contents = list()
					for linked_resource in contents:
						if isinstance(linked_resource, dict) and "relative_path" in linked_resource and "output_path" in linked_resource:
							self.latest_contents.append(linked_resource)
					if len(self.latest_contents) == 0:
						del self.latest_contents
			except json.JSONDecodeError:
				attention(f"Malformed {basename(self.contents_path)!r}, prebuilt contents will be ignored...")

	def save_contents(self):
		ensure_file(self.contents_path)
		with open(self.contents_path, "w", encoding="utf-8") as contents_file:
			json.dump(self.contents, contents_file, indent=None, ensure_ascii=False)
		if hasattr(self, "latest_contents"):
			del self.latest_contents

	def append_resource(self, relative_path: str, output_path: str, **properties: Any) -> None:
		for linked_resource in self.contents:
			if relative_path == linked_resource["relative_path"] and output_path == linked_resource["output_path"]:
				attention(f"Duplicate resource directory {relative_path!r}, skipping it...")
				return
		self.contents.append({
			"relative_path": relative_path,
			"output_path": output_path,
			**{ key: value for key, value in properties.items() if value is not None }
		})

	def iterate_resources(self):
		if len(self.contents) > 0 and hasattr(self, "latest_contents"):
			attention(f"There is cached and runtime contents at same time, this can lead to duplication of some resources. If you are an extension developer, please make sure that your LinkedResourceStorage is stored.")
		for linked_resource in self.contents:
			yield linked_resource
		if hasattr(self, "latest_contents"):
			for linked_resource in self.latest_contents:
				yield linked_resource
