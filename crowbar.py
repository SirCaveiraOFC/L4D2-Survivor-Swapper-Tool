# -*- coding: utf-8 -*-

import pyautogui
import time
import subprocess
import psutil

__crowbar_version__ = "0.74"  # Crowbar Version

def is_crowbar_running():
	"""Check if the Crowbar process is running."""
	for process in psutil.process_iter(['name']):
		if process.info['name'] == 'Crowbar.exe':
			return True
	return False

class Crowbar:
	@staticmethod
	def click(action_name):
		"""Click a button based on the action name."""
		# Move the window to the top left corner
		if is_crowbar_running():
			pyautogui.getWindowsWithTitle("Crowbar")[0].moveTo(0, 0)

		# Define coordinates for each action
		coordinates = {
			"compile_tab": (354, 41),
			"compile": (76, 360),
			"decompile_tab": (291, 41),
			"decompile": (73, 379),
			"mdl_input": (433, 64),  # Coordinates for the model input box
			"close_crowbar": (766, 15)
		}

		# Get the coordinates for the requested action
		coords = coordinates.get(action_name)

		if coords:
			pyautogui.click(*coords)  # Perform the click at the coordinates
			print("Clicked on: {}".format(action_name))
		else:
			print("Action '{}' not recognized.".format(action_name))
			
	@staticmethod
	def fill_mdl_input(text):
		"""Click on the text box, clear it, and fill it with text."""
		coords = (433, 64) # Coordinates for the text box

		if coords:
			pyautogui.click(*coords)  # Click on the text box
			print(f"Clicked on: fill_mdl_input")
			time.sleep(0.5)  # Wait for the text box to become active
			pyautogui.hotkey('ctrl', 'a')  # Select all text
			print(f"Selected on: fill_mdl_input_text")
			pyautogui.press('backspace')  # Clear the text
			print(f"Backspace on: fill_mdl_input_text")
			pyautogui.write(text)  # Fill in with the new text
			print(f"Filled on: fill_mdl_input_text")

def wait_for_mouse_to_stop(callback, wait_time=2):
	"""Wait for the mouse to stop moving for a specified time, then call the callback."""
	last_position = None
	pause_time = 0  # Time the mouse has been stationary

	while is_crowbar_running():
		current_position = pyautogui.position()  # Get the current mouse position

		# Check if the current position is the same as the last
		if current_position == last_position:
			pause_time += 1  # Increment pause time
		else:
			pause_time = 0  # Reset pause time
			last_position = current_position  # Update last position

		# If the mouse has been stationary for the specified time, execute the callback
		if pause_time >= wait_time:
			callback()  # Call the provided callback function
			break  # Exit the loop after execution

		time.sleep(1)  # Wait 1 second before checking again

def check_image_on_screen(_type_):
	"""Checks if an image indicating a specific process type ('decompiled' or 'compiled') appears on the screen, 
	and waits until it is found. Continually searches for the specified image and logs status messages, 
	terminating when the image is detected."""
	image_path = ""

	if _type_ == "decompiled":
		image_path = "decompiled_message.png"
	elif _type_ == "compiled":
		image_path = "compiled_message.png"

	while True:
		print("[+] Searching for {} message...".format(_type_.capitalize()))

		# Checks if the image is on the screen
		try:
			location = pyautogui.locateOnScreen(image_path)

			if location is not None:
				print("\n[+] {} successfully!\n".format(_type_.capitalize()))
				break
			else:
				pass
		except:
			pass

def run_crowbar():
	# Start the Crowbar program
	subprocess.Popen(['./Crowbar.exe'])

	print("\n[+] Started Crowbar.exe\n")

if __name__ == "__main__":
	run_crowbar()
	pyautogui.displayMousePosition()