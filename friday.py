import os
import json
import time
import pyautogui
import subprocess
import base64
import io
from PIL import Image
from groq import Groq

# SAFETY PROTOCOL: NEVER TYPE API KEYS HERE
# We fetch the key safely from Windows Environment Variables
API_KEY = os.environ.get("GROQ_API_KEY")

if not API_KEY:
    print("ERROR: GROQ_API_KEY environment variable missing!")
    print("Please run this command in PowerShell:")
    print('[System.Environment]::SetEnvironmentVariable("GROQ_API_KEY", "YOUR_KEY", "User")')
    exit()

# Initialize Client
client = Groq(api_key=API_KEY)
# 2. Set up the conversation history with a FRIDAY persona
messages = [
    {
        "role": "system",
        "content": "You are FRIDAY, a highly intelligent, autonomous AI assistant with full administrative control over this Windows PC. You can see the screen, read/write files, and execute code. Speak clearly and concisely."
    }
]

# 3. Define the "Tools" (God Mode + Vision)
tools = [
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": "Open a specific application on the user's Windows PC.",
            "parameters": {
                "type": "object",
                "properties": {
                    "app_name": {"type": "string", "description": "The name of the application to open, e.g., 'word', 'notepad', 'chrome'."}
                },
                "required": ["app_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_url",
            "description": "Opens a specific URL in the Microsoft Edge web browser.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The full URL to open."}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "type_on_keyboard",
            "description": "Types text on the keyboard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The exact text to type."}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "press_hotkey",
            "description": "Presses a combination of keys on the keyboard.",
            "parameters": {
                "type": "object",
                "properties": {
                    "keys": {"type": "array", "items": {"type": "string"}, "description": "A list of keys to press together, e.g., ['ctrl', 's']."}
                },
                "required": ["keys"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Writes or saves text/code to a file on the computer.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "The full path where the file should be saved."},
                    "content": {"type": "string", "description": "The exact text or code to write into the file."}
                },
                "required": ["file_path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "execute_python_code",
            "description": "Writes and executes a Python script.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "The raw Python code to execute."}
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "visual_click",
            "description": "Takes a screenshot of the current screen, uses AI vision to find a specific button or element, and clicks it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "element_description": {"type": "string", "description": "Description of what to click, e.g., 'the Save button', 'the search bar', 'the Start menu'."}
                },
                "required": ["element_description"]
            }
        }
    }
]

# 4. Memory Manager
def manage_memory():
    if len(messages) > 15:
        del messages[1:-12] 

# 5. Helper function to take a screenshot
def take_screenshot_base64():
    screenshot = pyautogui.screenshot()
    buffered = io.BytesIO()
    screenshot.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

# 6. The actual Python functions that execute the actions
def execute_tool(tool_name, arguments):
    try:
        if tool_name == "open_application":
            app = arguments.get("app_name", "").lower()
            if 'word' in app: os.system("start winword")
            elif 'notepad' in app: os.system("start notepad")
            elif 'chrome' in app or 'edge' in app or 'browser' in app: os.system("start msedge")
            elif 'calculator' in app: os.system("start calc")
            else: os.system(f"start {app}")
            return f"Successfully initiated opening {app}."

        elif tool_name == "open_url":
            url = arguments.get("url", "")
            os.system(f'start msedge "{url}"')
            return f"Successfully opened {url} in Edge."

        elif tool_name == "type_on_keyboard":
            text = arguments.get("text", "")
            time.sleep(1) 
            pyautogui.write(text, interval=0.05)
            return f"Successfully typed: {text}"

        elif tool_name == "press_hotkey":
            keys = arguments.get("keys", [])
            time.sleep(0.5)
            pyautogui.hotkey(*keys)
            return f"Successfully pressed keys: {', '.join(keys)}"

        elif tool_name == "write_file":
            file_path = arguments.get("file_path", "")
            content = arguments.get("content", "")
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return f"Successfully wrote to {file_path}."

        elif tool_name == "execute_python_code":
            code = arguments.get("code", "")
            temp_file = "C:\\MARVEL\\FRIDAY\\temp_script.py"
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(code)
            result = subprocess.run(['python', temp_file], capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                return f"Code executed successfully. Output:\n{result.stdout}"
            else:
                return f"Code execution failed. Error:\n{result.stderr}"

        elif tool_name == "visual_click":
            element = arguments.get("element_description", "")
            print(f"[FRIDAY VISION] Taking screenshot to find: {element}...")
            
            base64_image = take_screenshot_base64()
            
            vision_response = client.chat.completions.create(
                model="llama-3.2-11b-vision-preview",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"Find the '{element}' on this screen. Return ONLY a JSON object with 'x' and 'y' coordinates of its center. Example: {{\"x\": 100, \"y\": 200}}. If not found, return {{\"x\": -1, \"y\": -1}}."},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                        ]
                    }
                ],
                temperature=0.1
            )
            
            response_text = vision_response.choices[0].message.content.strip()
            response_text = response_text.replace("```json", "").replace("```", "").strip()
            coords = json.loads(response_text)
            
            x, y = coords.get("x", -1), coords.get("y", -1)
            if x != -1 and y != -1:
                time.sleep(0.5)
                pyautogui.click(x, y)
                return f"Successfully found and clicked '{element}' at coordinates ({x}, {y})."
            else:
                return f"I could not find '{element}' on the screen."

        else:
            return f"Tool {tool_name} not found."
            
    except Exception as e:
        return f"Error executing tool: {str(e)}"

# 7. THE NEW AGENTIC LOOP
def chat_with_friday(user_input):
    messages.append({"role": "user", "content": user_input})
    manage_memory()

    # Loop up to 5 times to allow multiple tool calls in a row
    for _ in range(5):
        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            tools=tools,
            tool_choice="auto", 
            temperature=0.7,
        )

        msg = response.choices[0].message

        # If she doesn't want to use any more tools, she is done!
        if not msg.tool_calls:
            messages.append({"role": "assistant", "content": msg.content})
            return msg.content

        # She wants to use a tool, so we execute it
        messages.append(msg)
        for tool_call in msg.tool_calls:
            func_args = json.loads(tool_call.function.arguments)
            result = execute_tool(tool_call.function.name, func_args)
            
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result
            })
        manage_memory()

    return "I reached my maximum thinking limit for this task. Please try again."

# 8. The main loop
if __name__ == "__main__":
    print("System Online. Initializing FRIDAY protocol...")
    print("AGENTIC LOOP: Multi-step autonomous thinking enabled.")
    print("SAFETY: Move mouse to top-left corner to abort any action.")
    print("----------------------------------------")
    
    while True:
        user_input = input("You: ")
        
        if user_input.lower() in ['exit', 'quit']:
            print("FRIDAY: Shutting down. Goodbye!")
            break
            
        if not user_input.strip():
            continue

        try:
            response = chat_with_friday(user_input)
            print(f"Friday: {response}\n")
        except Exception as e:
            if "429" in str(e):
                print("Friday: I've hit the Groq speed limit. Please wait 10 seconds and try again.\n")
            else:
                print(f"Friday: I encountered an error: {e}\n")