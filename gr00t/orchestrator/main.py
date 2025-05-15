"""
Main entry point for the GR00T Orchestrator.
"""

import gradio as gr
from .ui_components import OrchestratorUI
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

def main():
    """Launch the GR00T Orchestrator UI."""
    ui = OrchestratorUI()
    app = ui.create_ui()
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False
    )

if __name__ == "__main__":
    main() 