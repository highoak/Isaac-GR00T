import runpod
import subprocess
import os
import json
import base64
import tempfile

def handler(event):
    """
    This generator processes incoming requests to your Serverless endpoint and
    executes a base64-encoded shell script. The script is decoded, saved to a temporary
    file, and executed. The output is streamed back to the caller in real-time.
    """

    print("Worker Start")
    input_data = event.get("input", {})

    # Get the base64 encoded script
    encoded_script = input_data.get("script")

    if not encoded_script:
        yield {
            "error": "No base64 encoded script provided in the input",
            "exit_code": 1
        }
        return

    try:
        # Decode the base64 script
        script_content = base64.b64decode(encoded_script).decode('utf-8')
        
        # Create a temporary file to store the script
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as temp_script:
            temp_script.write(script_content)
            script_path = temp_script.name

        # Make the script executable
        os.chmod(script_path, 0o755)

        print(f"Executing script from: {script_path}")

        # Start the subprocess and stream combined stdout & stderr
        process = subprocess.Popen(
            script_path,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Combine stderr with stdout for ordering
            text=True,
            bufsize=1                 # Line-buffered
        )

        # Yield output in real-time
        for line in iter(process.stdout.readline, ""):
            yield {"output": line.rstrip("\n")}

        # Wait for the process to finish and capture its exit code
        process.wait()
        
        # Clean up the temporary file
        os.unlink(script_path)
        
        yield {"exit_code": process.returncode}

    except Exception as e:
        yield {
            "error": str(e),
            "exit_code": 1
        }

# Start the Serverless function when the script is run
if __name__ == '__main__':
    runpod.serverless.start({
        'handler': handler,
        'return_aggregate_stream': True  # Enable streaming results back to the caller
    })