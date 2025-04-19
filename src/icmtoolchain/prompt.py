from abc import ABCMeta, abstractmethod
from typing import Any, Callable, Dict, Iterable, Optional, Sequence, Union

from prompt_toolkit import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.formatted_text import (AnyFormattedText,
                                           merge_formatted_text, to_plain_text)
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.key_binding.bindings.focus import (focus_next,
                                                       focus_previous)
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import (AnyContainer, HSplit, Layout,
                                   ScrollablePane, ScrollOffsets)
from prompt_toolkit.validation import Validator

from .shell import (Editable, Interactable, get_toolchain_style, pretty_print,
                    pretty_print_attention, pretty_print_failure,
                    pretty_print_success, pretty_print_yield)


class Feedback(metaclass=ABCMeta):
	def __init__(self, prompt: AnyFormattedText = "Ooh, was it supposed to be a query here?", fallback: object = None) -> None:
		self.prompt = prompt
		self.fallback = fallback

	@abstractmethod
	def create_content(self) -> AnyContainer:
		...

	@property
	def content(self) -> AnyContainer:
		if not hasattr(self, "_content"):
			self._content = self.create_content()
		return self._content

	def create_layout(self) -> Layout:
		return Layout(self.content)

	@property
	def layout(self) -> Layout:
		if not hasattr(self, "_layout"):
			self._layout = self.create_layout()
		return self._layout

	def create_key_bindings(self) -> KeyBindings:
		bindings = KeyBindings()

		@bindings.add("c-c")
		@bindings.add("<sigint>")
		def _(event: KeyPressEvent) -> None:
			event.app.exit(exception=KeyboardInterrupt())

		return bindings

	@property
	def key_bindings(self) -> KeyBindings:
		if not hasattr(self, "_key_bindings"):
			self._key_bindings = self.create_key_bindings()
		return self._key_bindings

	def create_application(self, bindings: Optional[KeyBindings] = None) -> Application:
		return Application(
			layout=self.layout,
			style=get_toolchain_style(),
			include_default_pygments_style=False,
			key_bindings=self.key_bindings,
			full_screen=False,
			mouse_support=True,
			erase_when_done=True,
		)

	@property
	def application(self) -> Application:
		if not hasattr(self, "_application"):
			self._application = self.create_application()
		return self._application

	def get_result(self) -> Optional[object]:
		self.inform_if_already_busy()
		return self.result if hasattr(self, "result") else self.fallback

	def pre_run(self) -> None:
		pass

	def inform_if_already_busy(self) -> None:
		if self.application.is_running:
			raise RuntimeError("Feedback is already requested, you cannot requery it until guest responds to ongoing one.")

	async def request_async(self) -> Any:
		self.inform_if_already_busy()
		self.result = await self.application.run_async(pre_run=self.pre_run)
		return self.result

	def request(self) -> Any:
		self.inform_if_already_busy()
		self.result = self.application.run(pre_run=self.pre_run)
		return self.result

	async def request_async_safe(self, prints_abort: bool = True) -> Any:
		try:
			return await self.request_async()
		except (KeyboardInterrupt, EOFError):
			if prints_abort:
				pretty_print_attention("Abort.")

	def request_safe(self, prints_abort: bool = True) -> Any:
		try:
			return self.request()
		except (KeyboardInterrupt, EOFError):
			if prints_abort:
				pretty_print_attention("Abort.")

	def print_result(self, result: object) -> object:
		if result is True:
			pretty_print_success(self.prompt, end=" ")
			pretty_print("Yes", style="class:print.answer")
		elif result is False:
			pretty_print_failure(self.prompt, end=" ")
			pretty_print("No", style="class:print.answer")
		elif result == "":
			pretty_print_attention(self.prompt, end=" ")
			pretty_print("<nope>", style="class:print.answer")
		elif result == self.fallback:
			pretty_print_yield(self.prompt, end=" ")
			pretty_print(result, style="class:print.answer")
		else:
			pretty_print_success(self.prompt, end=" ")
			pretty_print(result, style="class:print.answer")

	def complete(self, *, result: object = None, print_result: object = None) -> None:
		if self.application.is_running:
			self.application.exit(result=result)
		if result is not None:
			self.print_result(print_result if print_result else result)

class Input(Feedback):
	def __init__(
		self,
		prompt: AnyFormattedText = "How do you feel about typing?",
		hint: Optional[str] = None,
		explanation: AnyFormattedText = None,
		default_text: Optional[str] = None,
		use_hint_as_fallback: bool = True,
		fallback: object = None,
		on_input: Optional[Callable[['Input', str], None]] = None,
		on_validate: Optional[Callable[['Input', str], Optional[bool]]] = None,
		on_accept: Optional[Callable[['Input', str], Optional[bool]]] = None,
	):
		fallback = fallback if fallback is not None else (default_text or hint)
		Feedback.__init__(self, prompt=prompt, fallback=fallback)
		self.control_prompt = prompt
		self.hint = hint
		self.use_hint_as_fallback = use_hint_as_fallback
		self.explanation = explanation
		self.default_text = default_text
		self.on_input = on_input
		self.on_validate = on_validate
		self.on_accept = on_accept or on_validate
		self.read_only = False

	def create_content(self) -> AnyContainer:
		self.input_control = Editable(
			prompt=self.control_prompt,
			text=self.default_text or "",
			hint=self.hint,
			use_hint_as_fallback=self.use_hint_as_fallback,
			on_text_changed=self.on_text_changed,
			validator=Validator.from_callable(self.validator),
			accept_handler=self.accept_handler,
			read_only=self.read_only,
			idle_selector_text="",
			focused_selector_text=""
		)
		self.explanation_control = Interactable(text=lambda: self.explanation, style="class:editable.hint")

		return HSplit([
			self.input_control,
			self.explanation_control
		])

	def on_text_changed(self, buffer: Buffer) -> None:
		if self.on_input:
			self.on_input(self, buffer.text)

	def validator(self, text: str) -> bool:
		if self.on_validate:
			result = self.on_validate(self, text)
			if result is not None:
				return result
		return True

	def accept_handler(self, buffer: Buffer) -> bool:
		result = True
		if self.on_accept:
			result = self.on_accept(self, buffer.text)
		if result:
			has_text = buffer.text and len(buffer.text) > 0
			self.complete(result=buffer.text if has_text or not self.use_hint_as_fallback or not self.hint else self.hint)
		return result is True

class Confirm(Input):
	def __init__(
		self,
		prompt: AnyFormattedText = "Are you absolutely sure?",
		explanation: AnyFormattedText = None,
		default_value: bool = True,
		yes_or_no: AnyFormattedText = " (Y/n)",
		no_or_yes: AnyFormattedText = " (N/y)",
	):
		Input.__init__(self, prompt=prompt, hint="", explanation=explanation, fallback=default_value)
		self.control_prompt = merge_formatted_text([prompt, yes_or_no if default_value else no_or_yes])
		self.default_value = default_value
		self.read_only = True

	def create_key_bindings(self) -> KeyBindings:
		bindings = super().create_key_bindings()

		@bindings.add("y")
		@bindings.add("Y")
		def _(_: KeyPressEvent) -> None:
			self.complete(result=True)

		@bindings.add("n")
		@bindings.add("N")
		def _(_: KeyPressEvent) -> None:
			self.complete(result=False)

		@bindings.add(Keys.Enter)
		@bindings.add(" ")
		def _(_: KeyPressEvent) -> None:
			self.complete(result=self.default_value)

		return bindings

class Select(Feedback):
	def __init__(
		self,
		prompt: AnyFormattedText = "What do you like?",
		variants: Iterable[Optional[str]] = ["Rides", "Guide", "Both"],
		selected_variant: Optional[Union[int, str]] = None,
		default_variant: Optional[Union[int, str]] = None,
		returns_what: bool = False,
		explanation: AnyFormattedText = None,
		on_accept: Optional[Callable[['Select', str], Optional[bool]]] = None,
	):
		Feedback.__init__(self, prompt=prompt, fallback=default_variant)
		self.variants = variants
		self.selected_variant = selected_variant
		self.default_variant = default_variant
		self.returns_what = returns_what
		self.explanation = explanation
		self.on_accept = on_accept

	def create_content(self) -> AnyContainer:
		self.choice_variants: Sequence[AnyContainer] = []
		self.focused_interactable = None
		which_offset = 0
		for variant in self.variants:
			is_selected = self.selected_variant is not None and (
				variant == self.selected_variant or which_offset == self.selected_variant
			)
			interactable = Interactable(
				variant,
				focusable=True,
				show_cursor=False,
				style="class:selection" if is_selected else "",
				tag=which_offset
			)
			if self.default_variant and (variant == self.default_variant or which_offset == self.selected_variant):
				self.focused_interactable = interactable
			self.choice_variants.append(interactable)
			which_offset += 1
		self.explanation_control = Interactable(text=lambda: self.explanation, style="class:editable.hint")

		return HSplit([
			Interactable(self.prompt),
			ScrollablePane(
				HSplit(self.choice_variants),
				scroll_offsets=ScrollOffsets(3, 3),
				display_arrows=False,
			),
			self.explanation_control
		])

	def create_layout(self) -> Layout:
		return Layout(self.content, self.focused_interactable)

	def create_key_bindings(self) -> KeyBindings:
		bindings = super().create_key_bindings()

		bindings.add(Keys.Down)(focus_next)
		bindings.add(Keys.Up)(focus_previous)

		@bindings.add(Keys.Enter)
		@bindings.add(" ")
		def _(_: KeyPressEvent) -> None:
			text = None
			value = None
			if self.layout.current_control and isinstance(self.layout.current_control, Interactable):
				text = to_plain_text(self.layout.current_control.text)
				value = self.layout.current_control.tag
			elif self.default_variant is not None:
				if isinstance(self.default_variant, str):
					text = self.default_variant
					for control in self.layout.find_all_controls():
						if isinstance(control, Interactable) and text == to_plain_text(control.text):
							value = control.tag
							break
				else:
					value = self.default_variant
					for control in self.layout.find_all_controls():
						if isinstance(control, Interactable) and control.tag == self.default_variant:
							text = to_plain_text(control.text)
							break
			self.complete(result=text if self.returns_what else value, print_result=text)

		return bindings

class Review:
	def __init__(self, **feedback: Union[Optional[Feedback], Callable[['Review'], Optional[Feedback]]]) -> None:
		self.current_feedback = None
		self.feedback_keys = [entry for entry in feedback]
		self.feedback_callables = {
			entry: feedback[entry] for entry in feedback
		}

	def request_feedback(self) -> Optional[Feedback]:
		if not hasattr(self, "current_offset"):
			raise ValueError("Review#request_feedback: Review.current_offset")
		if hasattr(self, "current_feedback") and self.current_feedback is not None:
			self.current_feedback.inform_if_already_busy()

		self.current_feedback = None
		self.current_key = None
		while self.current_feedback is None:
			self.current_offset += 1
			if len(self.feedback_keys) <= self.current_offset:
				break

			feedback_key = self.feedback_keys[self.current_offset]
			if not feedback_key or not feedback_key in self.feedback_callables:
				continue

			feedback = self.feedback_callables[feedback_key]
			if callable(feedback):
				feedback = feedback(self)
			if feedback is not None:
				self.current_key = feedback_key
			self.current_feedback = feedback

		return self.current_feedback

	def receive_feedback(self, returns_empty_properties: bool = False) -> Optional[object]:
		if not hasattr(self, "current_feedback") or self.current_feedback is None or \
				not hasattr(self, "current_key") or self.current_key is None:
			raise ValueError("Review#receive_feedback: Review.current_feedback or Review.current_key")
		if not hasattr(self, "results") or self.results is None:
			raise ValueError("Review#receive_feedback: Review.results")
		self.current_feedback.inform_if_already_busy()

		result = self.current_feedback.get_result()
		if result is not None or returns_empty_properties:
			self.results[self.current_key] = result
		return result

	def request(self, returns_empty_properties: bool = False) -> Dict[str, Any]:
		assert not self.current_feedback
		self.results = {}
		self.current_offset = -1
		while True:
			feedback = self.request_feedback()
			if not feedback:
				break
			feedback.request()
			self.receive_feedback(returns_empty_properties=returns_empty_properties)
		self.current_feedback = None
		return self.results

	async def request_async(self, returns_empty_properties: bool = False) -> Any:
		assert not self.current_feedback
		self.results = {}
		self.current_offset = -1
		while True:
			feedback = self.request_feedback()
			if not feedback:
				break
			await feedback.request_async()
			self.receive_feedback(returns_empty_properties=returns_empty_properties)
		self.current_feedback = None
		return self.results

	def request_safe(self, prints_abort: bool = True, returns_empty_properties: bool = False) -> Optional[Dict[str, Any]]:
		try:
			return self.request(returns_empty_properties=returns_empty_properties)
		except (KeyboardInterrupt, EOFError):
			if prints_abort:
				pretty_print_attention("Abort.")

	async def request_async_safe(self, prints_abort: bool = True, returns_empty_properties: bool = False) -> Optional[Dict[str, Any]]:
		try:
			return await self.request_async(returns_empty_properties=returns_empty_properties)
		except (KeyboardInterrupt, EOFError):
			if prints_abort:
				pretty_print_attention("Abort.")

if __name__ == "__main__":
	from random import randint
	templates_available = randint(0, 1) == 0
	results = Review(
		template=lambda review: Select(
			"Which template should be used?",
			variants=["Mod Template (../toolchain-mod-template)", "Modding Tools Template (../template-assistant)"],
			explanation="Templates are used to provide initial project description, create initial files, and more."
		) if templates_available else None,
		name=Input("Decide a name for your project:", hint="Template Mod"),
		author=Input("Author who crafted this creation:", hint="Reider746"),
		version=Input("What version a project starts from:", hint="1.0"),
		description=Input("Describe this masterpiece in one sentence:"),
		client_side=Confirm("Is it a client mod that not requires server?", default_value=False)
	).request_safe()
	print(results)
