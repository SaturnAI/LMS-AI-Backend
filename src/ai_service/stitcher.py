import json

from src.cred import Credentials
from src.schema import JSONSchema


class Stitcher:
    def stitch_context(self, filename: str) -> str:
        """It makes context for AI calls

        Returns:
            str: context for AI calls
        """
        json_schema = Stitcher.get_json_schema(filename=filename)
        context = "[Role]: " + json_schema.role + "\n\n"

        for description in json_schema.description:
            context += description + "\n"

        context += "\n[Instructions]: " + json_schema.instructions + "\n\n"
        context += "[Examples]->\n\n"

        if json_schema.examples:
            for example in json_schema.examples:
                if isinstance(example.user_prompt, list):
                    example.user_prompt = "\n".join(example.user_prompt)

                # Append user input and output to context
                context += "[User Input]:\n" + str(example.user_prompt) + "\n"
                completion = example.completion
                if isinstance(completion, dict) and isinstance(completion.get("answer"), str):
                    example_output = completion.get("answer")
                else:
                    example_output = json.dumps(completion)

                context += "\n[Output]:\n" + str(example_output) + "\nEND\n\n"

        if json_schema.important_notes:
            context += "[Important Notes]:\n"
            for important_note in json_schema.important_notes:
                context += important_note + "\n"

        return context

    @staticmethod
    def get_json_schema(filename: str) -> JSONSchema:
        """It makes schema for AI calls

        Returns:
            object: schema
        """
        file = open(Credentials.directory + f"/src/ai_service/{filename}.json")
        json_schema = JSONSchema.model_validate(json.load(file))
        file.close()
        return json_schema
