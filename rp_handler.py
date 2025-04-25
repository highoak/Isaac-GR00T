import runpod
import subprocess
import os
import json

def handler(event):
    """
    This function processes incoming requests to your Serverless endpoint.
    It executes the provided bash command and returns the output.
    
    Args:
        event (dict): Contains the input data and request metadata
        
    Returns:
        dict: Contains the command output, error (if any), and exit code
    """
    
    # Extract input data
    print(f"Worker Start")
    input_data = event['input']
    
    # Get the command to execute
    command = input_data.get('command')
    
    if not command:
        return {
            "error": "No command provided in the input",
            "exit_code": 1
        }
    
    print(f"Executing command: {command}")
    
    try:
        # Execute the command and capture output
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        stdout, stderr = process.communicate()
        exit_code = process.returncode
        
        return {
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code
        }
    
    except Exception as e:
        return {
            "error": str(e),
            "exit_code": 1
        }

# Start the Serverless function when the script is run
if __name__ == '__main__':
    runpod.serverless.start({'handler': handler})