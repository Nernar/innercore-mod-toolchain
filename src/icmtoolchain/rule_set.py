from functools import lru_cache
from typing import (TYPE_CHECKING, Any, Dict, MutableSequence, MutableSet,
                    Optional, overload, override)

from .utils import ensure_not_whitespace

if TYPE_CHECKING:
	from .config import Config


class RuleSet:
	rules: Dict[str, MutableSet[str]]
	rule_values: MutableSet[str]

	def __init__(self, prototype_set: Optional['RuleSet'] = None) -> None:
		self.rules = dict()
		self.rule_values = set()
		if prototype_set:
			self.extend_with_rules(prototype_set)

	def append_rule(self, rule: str, *values: str) -> None:
		if not rule in self.rules:
			self.rules[rule] = set()
		rules = self.rules[rule]
		for value in values:
			if value in rules:
				continue
			if value in self.rule_values:
				raise ValueError(f"Rule {rule} contains value {value!r} which is already occupied by another rule!")
			rules.add(value)

	def remove_rule(self, rule: str) -> None:
		if not rule in self.rules:
			return
		for value in self.rules[rule]:
			self.rule_values.remove(value)
		del self.rules[rule]

	def extend_with_rules(self, set: 'RuleSet') -> None:
		for rule in set.rules:
			self.append_rule(rule, *set.rules[rule])

	def rule_of(self, value: str) -> Optional[str]:
		if not value in self.rule_values:
			return
		for rule in self.rules:
			for rule_value in self.rules[rule]:
				if value == rule_value:
					return rule

	def bisect_values(self, properties: MutableSequence[str], *values: str) -> None:
		for value in values:
			rule = self.rule_of(value)
			if not rule or not rule in self.rules:
				continue
			for rule_value in self.rules[rule]:
				if rule_value in properties:
					properties.remove(rule_value)
		for value in values:
			properties.append(value)

	def remove_values(self, properties: MutableSequence[str], rule: str) -> None:
		if not rule in self.rules:
			return
		for value in self.rules[rule]:
			if value in properties:
				properties.remove(value)

	def is_relevant(self, properties: MutableSequence[str], value_set: str, allow_unresolved_properties: bool = True) -> bool:
		if not ensure_not_whitespace(value_set) or value_set == "*":
			return True
		values = value_set.split("-")
		for value in values:
			if not value in properties:
				return False
			if not allow_unresolved_properties and not value in self.rule_values:
				# Most likely a console property that cannot be checked here.
				return False
		return True

TOOLCHAIN_RULE_SET = RuleSet()
TOOLCHAIN_RULE_SET.append_rule("package_type", "develop", "release")
TOOLCHAIN_RULE_SET.append_rule("native_architecture", "arm", "arm64", "x86", "x86_64")


@lru_cache(maxsize=4096)
def get_config_rule_set(type: Optional[type['Config']]):
	if not type:
		if not TYPE_CHECKING:
			from .config import Config
		type = Config
	class RuleSetConfig(type):
		pass
	return RuleSetConfig
