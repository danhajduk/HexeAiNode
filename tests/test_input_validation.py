import unittest

from ai_node.execution.input_validation import validate_and_normalize_task_inputs


class InputValidationTests(unittest.TestCase):
    def test_email_family_normalizes_subject_and_body(self):
        result = validate_and_normalize_task_inputs(
            task_family="task.classification.email",
            inputs={"subject": "Hello", "body": "Please classify this message"},
        )

        self.assertEqual(result.prompt, "Subject: Hello\n\nPlease classify this message")
        self.assertEqual(result.metadata["email_subject"], "Hello")

    def test_image_family_accepts_image_url_without_prompt(self):
        result = validate_and_normalize_task_inputs(
            task_family="task.classification.image",
            inputs={"image_url": "https://example.com/cat.png"},
        )

        self.assertEqual(result.prompt, "Classify the provided image input.")
        self.assertEqual(result.metadata["image_url"], "https://example.com/cat.png")

    def test_messages_are_normalized_and_validated(self):
        result = validate_and_normalize_task_inputs(
            task_family="task.summarization.text",
            inputs={"messages": [{"role": " user ", "content": " hello "}]},
        )

        self.assertEqual(result.messages, [{"role": "user", "content": "hello"}])

    def test_invalid_temperature_is_rejected(self):
        with self.assertRaises(ValueError) as context:
            validate_and_normalize_task_inputs(
                task_family="task.summarization.text",
                inputs={"text": "hello", "temperature": 3.0},
            )

        self.assertEqual(str(context.exception), "invalid_input")


if __name__ == "__main__":
    unittest.main()
