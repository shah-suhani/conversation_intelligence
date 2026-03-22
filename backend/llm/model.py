import os
import yaml
from dotenv import load_dotenv
from langchain_community.chat_models import ChatOllama

load_dotenv()

from langchain_openai import ChatOpenAI

# Import metrics callback for automatic usage tracking
try:
    from utils.metrics_callback import get_metrics_handler
    _metrics_handler = get_metrics_handler()
except ImportError:
    _metrics_handler = None
                

class LLMFactory:
    def __init__(self, config_path: str, enable_metrics: bool = True):
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)["llm"]

        self.provider = config["provider"].lower()
        self.model = config["model"]
        self.api_key = None
        self.enable_metrics = enable_metrics and _metrics_handler is not None
        self.kwargs = {k: v for k, v in config.items()
                       if k not in ["provider", "model", "api_key"]}
        
        # Add metrics callback if enabled
        if self.enable_metrics:
            existing_callbacks = self.kwargs.get("callbacks", [])
            if _metrics_handler not in existing_callbacks:
                self.kwargs["callbacks"] = existing_callbacks + [_metrics_handler]

        self._set_env_key()
        self.llm = self._load_model()

    def _set_env_key(self):
        if self.provider == "gemini":
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                self.api_key = os.environ["GOOGLE_API_KEY"] 
            except ImportError:
                raise ImportError("langchain_google_genai is required for Gemini provider")

        elif self.provider == "openai":
            try:
                self.api_key = os.environ["OPENAI_API_KEY"]
            except ImportError:
                raise ImportError("langchain_openai is required for OpenAI provider")
            

        elif self.provider == "hf":
            try:
                from langchain_community.llms import HuggingFaceHub
                self.api_key = os.environ["HUGGINGFACEHUB_API_KEY"]
            except ImportError:
                raise ImportError("langchain_community is required for HuggingFace provider")


    def _load_model(self):
        if self.provider == "gemini":
            return ChatGoogleGenerativeAI(model=self.model, **self.kwargs)

        elif self.provider == "openai":
            return ChatOpenAI(model=self.model, **self.kwargs)

        elif self.provider == "hf":
            return HuggingFaceHub(
                repo_id=self.model,
                task="text-generation",
                **self.kwargs
            )

        elif self.provider == "ollama":
            try:
                from langchain_community.chat_models import ChatOllama
            except ImportError:
                raise ImportError("langchain_community is required for Ollama provider")
            ChatOllama(model=self.model, **self.kwargs)

        else:
            raise ValueError(f"Unknown provider: {self.provider}")

    def invoke(self, prompt):
        return self.llm.invoke(prompt)

    def stream(self, prompt):
        for chunk in self.llm.stream(prompt):
            yield chunk


if __name__ == "__main__":
    model = LLMFactory("../config.yaml")
    print(model.invoke("Hello").content)