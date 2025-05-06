from json import JSONDecodeError
from json import dump as dump_json
from json import load as load_json
from os.path import (abspath, basename, dirname, exists, isfile, join,
                     normpath, relpath)
from typing import (Any, Iterable, MutableMapping, MutableSequence, Optional,
                    Protocol, Union, override)

from .utils import ensure_file


class SupportsKeysAndGetItemConfig(Protocol):
    def keys(self) -> Iterable[str]: ...
    def __getitem__(self, key: str, /) -> Any: ...

class Config(dict[str, Any]):
	def __init__(self, map: Optional[SupportsKeysAndGetItemConfig] = None, defaults: Optional['Config'] = None):
		if map is not None:
			super().__init__(map)
		else:
			super().__init__()
		self.defaults = defaults

	def is_supported_value(self, value: Any) -> bool:
		return value is None \
			or isinstance(value, int) \
			or isinstance(value, float) \
			or isinstance(value, bool) \
			or isinstance(value, str) \
			or isinstance(value, MutableSequence) \
			or isinstance(value, MutableMapping)

	def get_value(self, key: str, fallback: Any = None, *, allow_prototype: bool = True) -> Any:
		try:
			return self.get_value_unsafe(key)
		except KeyError:
			if self.defaults is not None and allow_prototype:
				return self.defaults.get_value(key, fallback)
		return fallback

	def get_value_unsafe(self, key: str) -> Any:
		if not "." in key:
			return super().__getitem__(key)

		namespace_keys = key.partition(".")
		namespace = super().__getitem__(namespace_keys[0])
		if not isinstance(namespace, Config):
			raise KeyError(key)

		return namespace.get_value_unsafe(namespace_keys[2])

	@override
	def __getitem__(self, key: str, /) -> Any:
		return self.get_value_unsafe(key)

	def obtain_config(self, key: str, *, allow_prototype: bool = True) -> 'Config':
		value = self.get_value(key, allow_prototype=allow_prototype)
		if isinstance(value, Config):
			return value
		value = self.replace_value(value)
		if not isinstance(value, Config):
			value = Config()
		self.set_value(key, value)
		return value

	def set_value(self, key: str, value: Any, strip_none_from_lists: bool = False) -> None:
		self.set_value_unsafe(key, value, replace_mismatched_types=True, strip_none_from_lists=strip_none_from_lists)

	def set_value_unsafe(self, key: str, value: Any, *, replace_mismatched_types: bool = False, strip_none_from_lists: bool = False):
		if not self.is_supported_value(value):
			raise ValueError(f"Config value should be primitive, array or nested config, got {key!r}: {type(value)}!")
		if not "." in key:
			super().__setitem__(key, self.replace_value(value, strip_none_from_lists=strip_none_from_lists))
			return

		namespace_keys = key.partition(".")
		namespace = super().__getitem__(namespace_keys[0])
		if not isinstance(namespace, Config):
			if not replace_mismatched_types:
				raise ValueError(f"{key!r}: {namespace}")
			namespace = Config()
			super().__setitem__(namespace_keys[0], namespace)

		namespace.set_value_unsafe(namespace_keys[2], value, replace_mismatched_types=replace_mismatched_types)

	def replace_value(self, obj: Any, strip_none_from_lists: bool = False) -> Any:
		if not self.is_supported_value(obj):
			return None
		if isinstance(obj, MutableMapping) and not isinstance(obj, Config):
			return Config(map=obj)
		if isinstance(obj, MutableSequence):
			for offset, value in enumerate(obj):
				obj[offset] = self.replace_value(value, strip_none_from_lists=strip_none_from_lists)
			if strip_none_from_lists:
				while None in obj:
					obj.remove(None)
		return obj

	@override
	def __setitem__(self, key: str, value: Any, /) -> None:
		self.set_value_unsafe(key, value, replace_mismatched_types=True)

	def merge_config(self, config: Union[dict, 'Config'], *, replace_configs: bool = False, extend_lists: bool = False, strip_none_from_lists: bool = False) -> None:
		for key, value in config.items():
			if not key in self:
				super().__setitem__(key, self.replace_value(value, strip_none_from_lists=strip_none_from_lists))
				continue

			current_value = super().__getitem__(key)
			if not replace_configs and isinstance(value, Config) and isinstance(current_value, Config):
				current_value.merge_config(value, extend_lists=extend_lists, strip_none_from_lists=strip_none_from_lists)
				continue
			if extend_lists and isinstance(value, MutableSequence) and isinstance(current_value, MutableSequence):
				current_value.extend(value)
				continue

			super().__setitem__(key, self.replace_value(value, strip_none_from_lists=strip_none_from_lists))

	def delete_value(self, key: str, *, remove_when_empty: bool = True) -> None:
		self.delete_value_unsafe(key, remove_mismatched_types=True, remove_when_empty=remove_when_empty)

	def delete_value_unsafe(self, key: str, *, remove_mismatched_types: bool = False, remove_when_empty: bool = True) -> None:
		if not "." in key:
			super().__delitem__(key)
			return

		namespace_keys = key.partition(".")
		namespace = super().__getitem__(namespace_keys[0])
		if not isinstance(namespace, Config):
			if remove_mismatched_types:
				super().__delitem__(key)
				return
			raise ValueError(f"{key!r}: {namespace}")

		namespace.delete_value_unsafe(namespace_keys[2], remove_mismatched_types=remove_mismatched_types, remove_when_empty=remove_when_empty)
		if remove_when_empty:
			for _ in namespace:
				return
			super().__delitem__(key)

	@override
	def __delitem__(self, key: str, /) -> None:
		self.delete_value_unsafe(key, remove_mismatched_types=True)

	def as_json(self, *, strip_none: bool = True) -> dict:
		json = {}
		for key, value in self.items():
			if not isinstance(value, Config):
				continue
			json[key] = value.as_json(strip_none=strip_none)
		for key, value in self.items():
			if isinstance(value, Config) or (
				strip_none and value is None
			):
				continue
			if isinstance(value, MutableSequence):
				value = [
					obj.as_json(strip_none=strip_none) if isinstance(obj, Config) \
						else obj for obj in value if not strip_none or obj is not None
				]
			json[key] = value
		return json

class FileConfig(Config):
	def __init__(self, path: str, defaults: Optional['Config'] = None, *, raise_non_existing: bool = False):
		super().__init__(defaults=defaults)
		self.path = path
		self.directory = dirname(abspath(path))
		self.read_from_file(raise_non_existing=raise_non_existing)

	def read_from_file(self, *, raise_non_existing: bool = True, merge_with_existing: bool = False) -> None:
		non_existing = not isfile(self.path)
		if raise_non_existing and non_existing:
			raise ValueError(f"{self.path} does not exist!")
		if not merge_with_existing:
			self.clear()
		if non_existing:
			return

		with open(self.path, encoding="utf-8") as file:
			try:
				config = load_json(file)
				if not merge_with_existing:
					self.update(config)
					return
				self.merge_config(Config(config))
			except JSONDecodeError as exc:
				raise ValueError(f"Malformed {basename(self.path)!r}, you should fix it! {exc.msg}")

	def save_as_file(self, output_path: Optional[str] = None) -> None:
		path_to_save = output_path or self.path
		if not isfile(path_to_save):
			ensure_file(path_to_save)

		with open(path_to_save, "w", encoding="utf-8") as file:
			try:
				dump_json(self.as_json(), file)
				file.write("\n")
			except TypeError as exc:
				raise ValueError(f"Malformed config {path_to_save!r} due to internal error! {exc}")

	def get_relative_path(self, path_from_config: str) -> str:
		return abspath(join(self.directory, normpath(path_from_config)))

	def get_path(self, path_from_config: str) -> str:
		relative_path = self.get_relative_path(path_from_config)
		absolute_path = abspath(path_from_config)
		return absolute_path if not exists(relative_path) and exists(absolute_path) else relative_path

	def get_path_to_config(self, path_from_config: str) -> str:
		absolute_path = self.get_path(path_from_config)
		return relpath(absolute_path, self.directory)
