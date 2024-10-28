# -*- coding: utf-8 -*-

from pathlib import Path
from crowbar import (
	__crowbar_version__,
	is_crowbar_running,
	Crowbar,
	wait_for_mouse_to_stop,
	run_crowbar,
	check_image_on_screen
)
from qc_file_handler import QCFileHandler  # Import the QCFileHandler

import os
import subprocess
import sys
import psutil
import time
import json
import shutil
import pyautogui
import traceback
import re

os.system("color 5")  # Purple CMD Color

# Tool Informations
__developer__ = "Sr.Caveira | 頭蓋骨 </> Dark'"  # Tool Developer
__version__ = "1.0.0"  # Tool Version

clear = lambda: os.system("cls" if os.name == "nt" else "clear")  # Clear Screen
pause = lambda: os.system("pause")  # Pause

# Survivor Origin Variables
survivor_origin = None
survivor_origin_folder = None

# Survivor Destination Variables
survivor_destination = None
survivor_destination_folder = None
survivor_destination_final_folder = None

# Settings
vpk_executable = None  # VPK Executable Path
delete_folders_when_swap = None
close_crowbar_when_swap = None

# addoninfo.txt Settings
addoninfo_content = None

# Survivor Attributes Dictionary
SurvivorAttributes = {
	# L4D1
	"bill": {
		"survivor_anims_folder": 'survivor_namvet_anims',
		"survivor_id": 'survivor_namvet',
		"survivor_model_file": 'survivor_namvet.mdl',
		"animation_code_list": [
			'$includemodel "survivors/anim_namvet.mdl"',
			'$includemodel "survivors/gestures_namvet.mdl"'
		],
		"fp_arms_name_list": {
			"dx90.vtx": 'v_arms_bill.dx90.vtx',
			"mdl": 'v_arms_bill.mdl',
			"vvd": 'v_arms_bill.vvd'
		},
		"vgui_name_list": {
			"lobby_icon": 'select_bill.vtf',
			"in_game_icon": 's_panel_namvet.vtf',
			"incap_icon": 's_panel_namvet_incap.vtf'
		}
	},
	"zoey": {
		"survivor_anims_folder": 'survivor_teenangst_anims',
		"survivor_id": 'survivor_teenangst',
		"survivor_model_file": 'survivor_teenangst.mdl',
		"animation_code_list": [
			'$includemodel "survivors/anim_teenangst.mdl"',
			'$includemodel "survivors/gestures_TeenAngst.mdl"'
		],
		"fp_arms_name_list": {
			"dx90.vtx": 'v_arms_zoey.dx90.vtx',
			"mdl": 'v_arms_zoey.mdl',
			"vvd": 'v_arms_zoey.vvd'
		},
		"vgui_name_list": {
			"lobby_icon": 'select_zoey.vtf',
			"in_game_icon": 's_panel_teenangst.vtf',
			"incap_icon": 's_panel_teenangst_incap.vtf'
		}
	},
	"louis": {
		"survivor_anims_folder": 'survivor_manager_anims',
		"survivor_id": 'survivor_manager',
		"survivor_model_file": 'survivor_manager.mdl',
		"animation_code_list": [
			'$includemodel "survivors/anim_Biker.mdl"',
			'$includemodel "survivors/gestures_biker.mdl"'
		],
		"fp_arms_name_list": {
			"dx90.vtx": 'v_arms_louis.dx90.vtx',
			"mdl": 'v_arms_louis.mdl',
			"vvd": 'v_arms_louis.vvd'
		},
		"vgui_name_list": {
			"lobby_icon": 'select_louis.vtf',
			"in_game_icon": 's_panel_manager.vtf',
			"incap_icon": 's_panel_manager_incap.vtf'
		}
	},
	"francis": {
		"survivor_anims_folder": 'survivor_biker_anims',
		"survivor_id": 'survivor_biker',
		"survivor_model_file": 'survivor_biker.mdl',
		"animation_code_list": [
			'$includemodel "survivors/anim_Biker.mdl"',
			'$includemodel "survivors/gestures_biker.mdl"'
		],
		"fp_arms_name_list": {
			"dx90.vtx": 'v_arms_francis.dx90.vtx',
			"mdl": 'v_arms_francis.mdl',
			"vvd": 'v_arms_francis.vvd'
		},
		"vgui_name_list": {
			"lobby_icon": 'select_francis.vtf',
			"in_game_icon": 's_panel_biker.vtf',
			"incap_icon": 's_panel_biker_incap.vtf'
		}
	},

	# L4D2
	"nick": {
		"survivor_anims_folder": 'survivor_gambler_anims',
		"survivor_id": 'survivor_gambler',
		"survivor_model_file": 'survivor_gambler.mdl',
		"animation_code_list": [
			'$includemodel "survivors/anim_gambler.mdl"',
			'$includemodel "survivors/anim_gestures.mdl"'
		],
		"fp_arms_name_list": {
			"dx90.vtx": 'v_arms_gambler_new.dx90.vtx',
			"mdl": 'v_arms_gambler_new.mdl',
			"vvd": 'v_arms_gambler_new.vvd'
		},
		"vgui_name_list": {
			"lobby_icon": 's_panel_lobby_gambler.vtf',
			"in_game_icon": 's_panel_gambler.vtf',
			"incap_icon": 's_panel_gambler_incap.vtf'
		}
	},
	"rochelle": {
		"survivor_anims_folder": 'survivor_producer_anims',
		"survivor_id": 'survivor_producer',
		"survivor_model_file": 'survivor_producer.mdl',
		"animation_code_list": [
			'$includemodel "survivors/anim_producer.mdl"',
			'$includemodel "survivors/anim_gestures.mdl"'
		],
		"fp_arms_name_list": {
			"dx90.vtx": 'v_arms_producer_new.dx90.vtx',
			"mdl": 'v_arms_producer_new.mdl',
			"vvd": 'v_arms_producer_new.vvd'
		},
		"vgui_name_list": {
			"lobby_icon": 's_panel_lobby_producer.vtf',
			"in_game_icon": 's_panel_producer.vtf',
			"incap_icon": 's_panel_producer_incap.vtf'
		}
	},
	"coach": {
		"survivor_anims_folder": 'survivor_coach_anims',
		"survivor_id": 'survivor_coach',
		"survivor_model_file": 'survivor_coach.mdl',
		"animation_code_list": [
			'$includemodel "survivors/anim_coach.mdl"',
			'$includemodel "survivors/anim_gestures.mdl"'
		],
		"fp_arms_name_list": {
			"dx90.vtx": 'v_arms_coach_new.dx90.vtx',
			"mdl": 'v_arms_coach_new.mdl',
			"vvd": 'v_arms_coach_new.vvd'
		},
		"vgui_name_list": {
			"lobby_icon": 's_panel_lobby_coach.vtf',
			"in_game_icon": 's_panel_coach.vtf',
			"incap_icon": 's_panel_coach_incap.vtf'
		}
	},
	"ellis": {
		"survivor_anims_folder": 'survivor_mechanic_anims',
		"survivor_id": 'survivor_mechanic',
		"survivor_model_file": 'survivor_mechanic.mdl',
		"animation_code_list": [
			'$includemodel "survivors/anim_producer.mdl"',
			'$includemodel "survivors/anim_gestures.mdl"'
		],
		"fp_arms_name_list": {
			"dx90.vtx": 'v_arms_mechanic_new.dx90.vtx',
			"mdl": 'v_arms_mechanic_new.mdl',
			"vvd": 'v_arms_mechanic_new.vvd'
		},
		"vgui_name_list": {
			"lobby_icon": 's_panel_lobby_mechanic.vtf',
			"in_game_icon": 's_panel_mechanic.vtf',
			"incap_icon": 's_panel_mechanic_incap.vtf'
		}
	}
}

def tool_header():
	"""Prints the header for the L4D2 Survivor Swapper Tool, displaying the developer's name, version, tips, and warnings."""
	global __version__
	header = """
╔════════════════════════════════════════════════════════════════════════════════╗
║                             L4D2 SURVIVOR SWAPPER TOOL                         ║
╠════════════════════════════════════════════════════════════════════════════════╣
║  Developer: Sr.Caveira (https://steamcommunity.com/id/srcaveira/)              ║
║  Version: {}                                                                ║
║                                                                                ║
║  Tips:                                                                         ║
║   - Don't move the mouse after the tool starts Crowbar;                        ║
║   - Always leave the "Survivor_Swap" folder clean before starting a new swap.  ║
║                                                                                ║
║  Warning:                                                                      ║
║   - This tool may not work on some skins.                                      ║
╚════════════════════════════════════════════════════════════════════════════════╝
	""".format(__version__)

	print(header)

def is_empty_dir(path):
	"""Checks if the specified directory is empty by verifying if it contains any files or subdirectories.
	Returns True if the directory is empty, otherwise returns False."""

	# Creates a Path object
	dir_path = Path(path)
	
	# Checks if the directory is empty
	if not any(dir_path.iterdir()):
		return True
	return False

def delete_survivor_folders():
	"""Deletes the survivor origin and destination folders if they exist, logging success or failure messages for each deletion."""
	global survivor_origin_folder
	global survivor_destination_folder

	# Delete the survivor_origin folder
	if os.path.exists(survivor_origin_folder):
		shutil.rmtree(survivor_origin_folder)
		print("[+] Successfully deleted the folder: {}".format(survivor_origin_folder))
	else:
		print("[!] The folder does not exist: {}".format(survivor_origin_folder))

	# Delete the survivor_destination folder
	if os.path.exists(survivor_destination_folder):
		shutil.rmtree(survivor_destination_folder)
		print("[+] Successfully deleted the folder: {}".format(survivor_destination_folder))
	else:
		print("[!] The folder does not exist: {}".format(survivor_destination_folder))

def main():
	global survivor_origin
	global survivor_destination
	global survivor_origin_folder
	global survivor_destination_folder
	global delete_folders_when_swap
	global close_crowbar_when_swap

	clear()
	load_settings()
	tool_header()

	survivor_origin, survivor_destination = choose_survivors()
	survivor_origin_folder = Path("./Survivor_Swap/{}".format(survivor_origin))
	survivor_destination_folder = Path("./Survivor_Swap/replace_{}".format(survivor_destination))

	choose_final_folder()
	copy_survivor_destination_from_kit()
	setup_addoninfo()
	copy_survivor_origin_materials()
	rename_survivor_origin_vtf_files()
	rename_survivor_origin_arms()
	run_crowbar()
	decompile_survivor_destination_mdl()
	decompile_survivor_origin_mdl()
	delete_hunk_files()
	replace_survivor_qc_file_strings()
	copy_survivor_origin_decompiled_files()
	compile_survivor_destination_qc_file()
	copy_survivor_destination_compiled_files()
	delete_decompiled_folder("destination", "survivors")
	decompile_survivor_origin_arms()
	replace_arms_qc_file_string()
	compile_survivor_origin_arms()
	copy_arms_origin_compiled_files()
	delete_decompiled_folder("origin", "arms")
	copy_survivor_origin_weapons()
	change_survivor_destination_folder_name()
	compile_vpk()

	if delete_folders_when_swap:
		delete_survivor_folders()

	if close_crowbar_when_swap:
		Crowbar.click("close_crowbar")

	pause()

def choose_survivors():
	"""Prompts the user to select origin and destination survivors for swapping, validating choices and allowing re-selection in case of invalid input."""
	clear()
	tool_header()

	survivors = ["Bill", "Zoey", "Louis", "Francis", "Nick", "Rochelle", "Coach", "Ellis"]

	print("[+] Choose the survivors for the swap:\n")

	# Display the list of survivors
	for i, survivor in enumerate(survivors, start=1):
		print("[{}] {}".format(i, survivor))

	try:
		# Request the choice for the origin
		origin = int(input("\n[+] Choose the origin survivor (type the number): "))

		# Request the choice for the destination
		destination = int(input("[+] Choose the destination survivor (type the number): "))
	except:
		return choose_survivors() # Calls the function again for new choice

	# Validation
	if (1 <= origin <= len(survivors) and 
		1 <= destination <= len(survivors) and
		origin != destination):
			survivor_origin = survivors[origin - 1]
			survivor_destination = survivors[destination - 1]

			print("\n[+] You chose: {} to {}.".format(survivor_origin, survivor_destination))

			return survivor_origin.lower(), survivor_destination.lower()
	else:
		clear()
		print("[!] Invalid choice. Please try again.")
		pause()
		clear()

		return choose_survivors() # Calls the function again for new choice

def choose_final_folder():
	"""Prompts the user to enter a name for the final folder, ensuring it does not contain invalid characters and is not empty, with the option to re-enter in case of an invalid input."""
	global survivor_destination_final_folder

	# Request the final folder name
	final_folder = input("\n[+] Choose the final folder name: ").strip()

	invalid_chars = ['\\', '/', ':', '*', '?', '"', '<', '>', '|']

	if not any(char in final_folder for char in invalid_chars) and final_folder.strip() != "":
		print("\n[+] You chose: {} for the final folder name.\n".format(final_folder))
		survivor_destination_final_folder = final_folder
	else:
		clear()
		print("[!] Invalid choice. Please try again.")
		pause()
		clear()
		return choose_final_folder() # Calls the function again for new choice

def setup_addoninfo():
	"""Sets up the addon information by loading an existing addoninfo.txt file, prompting the user for required and optional fields, validating input, and saving the updated content back to the file."""
	global survivor_destination_folder
	global addoninfo_content

	addoninfo_file = survivor_destination_folder / "addoninfo.txt"

	# Load the content of the addoninfo.txt file.
	try:
		with open(addoninfo_file, 'r', encoding='utf-8') as file:
			addoninfo_content = file.read()
	except FileNotFoundError:
		print("[!] File {} not found.".format(addoninfo_file))
		pause()
		return

	def get_addoninfo_item(key):
		global addoninfo_content
		return re.search(r'({}\s+"(.+?)")'.format(key), addoninfo_content, re.DOTALL)

	def set_addoninfo_value(item, value):
		global addoninfo_content
		addoninfo_content = addoninfo_content.replace(item.group(2), value)

	# Define addon fields with their prompts and whether they are required or optional
	addon_fields = {
		"AddonTitle": ("Choose the Addon Title: ", True),
		"AddonVersion": ("Optional - Choose the Addon Version (e.g.: 1.0): ", False),
		"AddonDescription": ("Optional - Choose the Addon Description: ", False),
		"AddonAuthor": ("Optional - Choose the Addon Author: ", False)
	}

	for key, (prompt, is_required) in addon_fields.items():
		while True:
			user_input = input("[+] {}".format(prompt))

			if is_required and user_input.strip() == "":  # Check if required and empty
				clear()
				print("[!] Invalid choice. Please try again.")
				pause()
				clear()
				return setup_addoninfo()  # Restart function for new choice
			elif user_input.strip() or is_required:  # Set value only if non-empty or required
				item = get_addoninfo_item(key)
				if item:
					set_addoninfo_value(item, user_input)
				break
			else:
				break  # Skip setting for optional empty input

	# Save the modified content back to the file
	with open(addoninfo_file, 'w', encoding='utf-8') as file:
		print("\n[+] {} has been successfully configured!\n".format(addoninfo_file))
		file.write(addoninfo_content)

def copy_survivor_destination_from_kit():
	"""Copies the survivor destination folder from the designated swap kit, ensuring the destination does not already exist, and handles any errors during the copy process."""
	global survivor_destination
	global survivor_destination_folder

	# Define source and destination paths
	source_path = Path("./HUNK'S_SURVIVOR_SWAP_KIT/replace_{}".format(survivor_destination))
	destination_path = survivor_destination_folder

	# Check if the destination already exists
	if not destination_path.exists():
		try:
			# Copy the directory tree
			shutil.copytree(source_path, destination_path, dirs_exist_ok=True)
			print("[+] Copy from '{}' to '{}' was successful.\n".format(source_path, destination_path))
		except Exception as e:
			print("[!] Error during copy: {}.".format(e))
			pause()
			clear()
	else:
		print("\n[!] The destination '{}' already exists. Copy was not performed.\n".format(destination_path))

def copy_survivor_origin_materials():
	"""Copies materials from the survivor origin folder to the destination folder, checking if the destination is empty and handling errors during the copy process."""
	global survivor_origin
	global survivor_destination
	global survivor_destination_folder
	global survivor_origin_folder

	# Define source and destination paths
	source_path = survivor_origin_folder / Path("materials/")
	destination_path = survivor_destination_folder / Path("materials/")

	# Check if the destination is empty
	if not destination_path.exists() or is_empty_dir(destination_path):
		try:
			# Copy the directory tree
			shutil.copytree(source_path, destination_path, dirs_exist_ok=True)
			print("[+] Copy from '{}' to '{}' was successful.".format(source_path, destination_path))
		except Exception as e:
			print("[!] Error during copy: {}. Press any key to try again.".format(e))
			pause()
			clear()
			return copy_survivor_origin_materials() # Calls the function again for new attemp to copy
	else:
		print("[!] The destination '{}' already has files. Copy was not performed.".format(destination_path))

def copy_survivor_origin_weapons():
	"""Copies weapon models from the survivor origin folder to the destination folder, ensuring the destination is empty and handling any errors that may occur during the copy process."""
	global survivor_destination
	global survivor_origin_folder
	global survivor_destination_folder

	# Define source and destination paths
	source_path = survivor_origin_folder / Path("models/weapons/")
	destination_path = survivor_destination_folder / Path("models/weapons/")

	# Check if the destination is empty
	if not destination_path.exists() or is_empty_dir(destination_path):
		try:
			# Copy the directory tree
			shutil.copytree(source_path, destination_path, dirs_exist_ok=True)
			print("[+] Copy from '{}' to '{}' was successful.".format(source_path, destination_path))
		except Exception as e:
			print("[!] Error during copy: {}.".format(e))
			pause()
			clear()
	else:
		print("[!] The destination '{}' already has files. Copy was not performed.".format(destination_path))

def rename_survivor_origin_vtf_files():
	"""Renames .VTF files in the survivor destination folder based on attributes of the origin and destination survivors, specifically for lobby, in-game, and incap icons, while ensuring the specified path exists."""
	global SurvivorAttributes
	global survivor_origin
	global survivor_destination
	global survivor_destination_folder

	# Define .VTF files path
	vtf_path = survivor_destination_folder / Path("materials/vgui/")

	# Checks if the path exists
	if vtf_path.exists() and vtf_path.is_dir():
		print("")
		# Cycle through all .vtf files in the vgui folder
		for vtf_file in vtf_path.glob("*.vtf"):
			new_vtf_name = None # Initialize new_vtf_name to None

			# Checks if the file matches an icon and sets the new name
			if vtf_file.name == SurvivorAttributes[survivor_origin]["vgui_name_list"]["lobby_icon"]:
				new_vtf_name = SurvivorAttributes[survivor_destination]["vgui_name_list"]["lobby_icon"]
			elif vtf_file.name == SurvivorAttributes[survivor_origin]["vgui_name_list"]["in_game_icon"]:
				new_vtf_name = SurvivorAttributes[survivor_destination]["vgui_name_list"]["in_game_icon"]
			elif vtf_file.name == SurvivorAttributes[survivor_origin]["vgui_name_list"]["incap_icon"]:
				new_vtf_name = SurvivorAttributes[survivor_destination]["vgui_name_list"]["incap_icon"]

			# If a new name has been defined, rename the file
			if new_vtf_name:
				new_vtf_path = vtf_path / new_vtf_name
				vtf_file.rename(new_vtf_path)
				print("[+] Renamed '{}' to '{}' successfully.".format(vtf_file.name, new_vtf_name))
			else:
				print("[!] No matching name for '{}'. File not renamed.".format(vtf_file.name))
	else:
		print("[!] The path '{}' does not exist or is not a directory.".format(vtf_path))

def rename_survivor_origin_arms():
	"""Renames survivor arm files in the origin folder based on the specified attributes for both the origin and destination survivors, handling files with extensions .dx90.vtx, .mdl, and .vvd, while ensuring the specified path exists."""
	global SurvivorAttributes
	global survivor_origin
	global survivor_destination
	global survivor_origin_folder

	# Define arms files path
	arms_path = survivor_origin_folder / Path("models/weapons/arms/")

	# Filter files with extensions .dx90.vtx, .mdl e .vvd
	filtered_arms_files = list(arms_path.glob('*.dx90.vtx')) + \
					list(arms_path.glob('*.mdl')) + \
					list(arms_path.glob('*.vvd'))

	# Checks if the path exists
	if arms_path.exists() and arms_path.is_dir():
		print("")
		# Cycle through all arms files in the arms folder
		for arm_file in filtered_arms_files:
			new_arm_name = None # Initialize new_arm_name to None

			# Checks if the file matches an icon and sets the new name
			if arm_file.name == SurvivorAttributes[survivor_origin]["fp_arms_name_list"]["dx90.vtx"]:
				new_arm_name = SurvivorAttributes[survivor_destination]["fp_arms_name_list"]["dx90.vtx"]
			elif arm_file.name == SurvivorAttributes[survivor_origin]["fp_arms_name_list"]["mdl"]:
				new_arm_name = SurvivorAttributes[survivor_destination]["fp_arms_name_list"]["mdl"]
			elif arm_file.name == SurvivorAttributes[survivor_origin]["fp_arms_name_list"]["vvd"]:
				new_arm_name = SurvivorAttributes[survivor_destination]["fp_arms_name_list"]["vvd"]

			# If a new name has been defined, rename the file
			if new_arm_name:
				new_arm_path = arms_path / new_arm_name
				arm_file.rename(new_arm_path)
				print("[+] Renamed '{}' to '{}' successfully.".format(arm_file.name, new_arm_name))
			else:
				print("\n[!] No matching name for '{}'. File not renamed.\n".format(arm_file.name))
	else:
		print("\n[!] The path '{}' does not exist or is not a directory.\n".format(arms_path))

def compile_survivor_destination_qc_file():
	"""Compiles the QC file for the specified survivor destination by interacting with the Crowbar tool, ensuring the compiled destination path is valid and waiting for mouse actions to complete."""
	global survivor_destination
	global SurvivorAttributes
	global survivor_destination_folder

	# Get the current working directory
	cwd = Path.cwd()

	# Define compiled destination path
	compiled_destination_path = survivor_destination_folder / Path("models/survivors/decompiled {}/compiled {}".format(__crowbar_version__, __crowbar_version__))

	# Define survivor destination qc file
	survivor_destination_qc_file = cwd / survivor_destination_folder / Path("models/survivors/decompiled {}/{}{}".format(__crowbar_version__, SurvivorAttributes[survivor_destination]["survivor_id"], ".qc"))

	if not compiled_destination_path.exists() or is_empty_dir(compiled_destination_path):
		wait_for_mouse_to_stop(lambda: Crowbar.click("compile_tab"))
		time.sleep(0.5)
		wait_for_mouse_to_stop(lambda: Crowbar.fill_mdl_input(str(survivor_destination_qc_file)))
		time.sleep(0.5)
		wait_for_mouse_to_stop(lambda: Crowbar.click("compile"))
		print("\n[+] Compiling '{}'\n".format(str(survivor_destination_qc_file)))
		check_image_on_screen("compiled")

def copy_survivor_destination_compiled_files():
	"""Copies the compiled survivor files from the specified source path to the destination path, ensuring the destination exists and handling any errors that may occur during the copy process."""
	global SurvivorAttributes
	global survivor_destination_folder

	# Define source and destination paths
	source_path = survivor_destination_folder / Path("models/survivors/decompiled {}/compiled {}/models".format(__crowbar_version__, __crowbar_version__))
	destination_path = survivor_destination_folder / Path("models/")

	# Check if the destination exists
	if destination_path.exists():
		try:
			# Copy the directory tree
			shutil.copytree(source_path, destination_path, dirs_exist_ok=True)
			print("[+] Copy from '{}' to '{}' was successful.".format(source_path, destination_path))
		except Exception as e:
			print("[!] Error during copy: {}. Press any key to try again.".format(e))
			pause()
			clear()
	else:
		print("[!] The destination '{}' doesn't exists.".format(destination_path))

def decompile_survivor_destination_mdl():
	"""Decompiles the specified survivor model file using Crowbar, waiting for the process to complete and handling the input/output paths accordingly."""
	global survivor_destination
	global SurvivorAttributes
	global survivor_destination_folder

	# Get the current working directory
	cwd = Path.cwd()

	# Define decompiled destination path
	decompiled_destination_path = survivor_destination_folder / Path("models/survivors/decompiled {}".format(__crowbar_version__))

	# Define survivor model file
	survivor_destination_model_file = cwd / survivor_destination_folder / Path("models/survivors/{}".format(SurvivorAttributes[survivor_destination]["survivor_model_file"]))

	time.sleep(5) # Wait for the Crowbar.exe

	if not decompiled_destination_path.exists():
		wait_for_mouse_to_stop(lambda: Crowbar.click("decompile_tab"))
		time.sleep(0.5)
		wait_for_mouse_to_stop(lambda: Crowbar.fill_mdl_input(str(survivor_destination_model_file)))
		time.sleep(0.5)
		wait_for_mouse_to_stop(lambda: Crowbar.click("decompile"))
		print("\n[+] Decompiling '{}'\n".format(str(survivor_destination_model_file)))
		check_image_on_screen("decompiled")

def decompile_survivor_origin_mdl():
	"""Decompiles the specified survivor origin model file using Crowbar, ensuring the output directory exists and handling the input/output paths accordingly."""
	global survivor_origin
	global SurvivorAttributes
	global survivor_origin_folder

	# Get the current working directory
	cwd = Path.cwd()

	# Define decompiled origin path
	decompiled_origin_path = survivor_origin_folder / Path("models/survivors/decompiled {}".format(__crowbar_version__))

	# Define survivor model file
	survivor_origin_model_file = cwd / survivor_origin_folder / Path("models/survivors/{}".format(SurvivorAttributes[survivor_origin]["survivor_model_file"]))

	if not decompiled_origin_path.exists():
		wait_for_mouse_to_stop(lambda: Crowbar.click("decompile_tab"))
		time.sleep(0.5)
		wait_for_mouse_to_stop(lambda: Crowbar.fill_mdl_input(str(survivor_origin_model_file)))
		time.sleep(0.5)
		wait_for_mouse_to_stop(lambda: Crowbar.click("decompile"))
		print("\n[+] Decompiling '{}'\n".format(str(survivor_origin_model_file)))
		check_image_on_screen("decompiled")

def decompile_survivor_origin_arms():
	"""Decompiles the specified survivor origin arms model file using Crowbar, ensuring the output directory exists and handling the input/output paths accordingly."""
	global survivor_destination
	global SurvivorAttributes
	global survivor_origin_folder

	# Get the current working directory
	cwd = Path.cwd()

	# Define decompiled origin path
	decompiled_origin_path = survivor_origin_folder / Path("models/weapons/arms/decompiled {}".format(__crowbar_version__))

	# Define survivor model file
	survivor_origin_model_file = cwd / survivor_origin_folder / Path("models/weapons/arms/{}".format(SurvivorAttributes[survivor_destination]["fp_arms_name_list"]["mdl"]))

	if not decompiled_origin_path.exists():
		wait_for_mouse_to_stop(lambda: Crowbar.click("decompile_tab"))
		time.sleep(0.5)
		wait_for_mouse_to_stop(lambda: Crowbar.fill_mdl_input(str(survivor_origin_model_file)))
		time.sleep(0.5)
		wait_for_mouse_to_stop(lambda: Crowbar.click("decompile"))
		print("\n[+] Decompiling '{}'\n".format(str(survivor_origin_model_file)))
		check_image_on_screen("decompiled")

def compile_survivor_origin_arms():
	"""Compiles the specified survivor origin arms model file using Crowbar, verifying the existence of the decompiled path and handling input/output paths accordingly."""
	global survivor_destination
	global SurvivorAttributes
	global survivor_origin_folder

	# Get the current working directory
	cwd = Path.cwd()

	# Define decompiled origin path
	decompiled_origin_path = survivor_origin_folder / Path("models/weapons/arms/decompiled {}".format(__crowbar_version__))

	# Define survivor model file
	survivor_origin_qc_file = cwd / survivor_origin_folder / Path("models/weapons/arms/decompiled {}/{}".format(__crowbar_version__, SurvivorAttributes[survivor_destination]["fp_arms_name_list"]["mdl"].replace(".mdl", ".qc")))

	if decompiled_origin_path.exists():
		wait_for_mouse_to_stop(lambda: Crowbar.click("compile_tab"))
		time.sleep(0.5)
		wait_for_mouse_to_stop(lambda: Crowbar.fill_mdl_input(str(survivor_origin_qc_file)))
		time.sleep(0.5)
		wait_for_mouse_to_stop(lambda: Crowbar.click("compile"))
		print("\n[+] Compiling '{}'\n".format(str(survivor_origin_qc_file)))
		check_image_on_screen("compiled")

def replace_arms_qc_file_string():
	"""Replaces the model name strings in the QC file for the survivor's arms. 
	This function updates the model name from the origin survivor to the destination survivor 
	within the specified QC file, ensuring the new model name is correctly referenced."""
	global survivor_origin
	global survivor_destination
	global SurvivorAttributes

	# Define decompiled origin path
	decompiled_origin_path = survivor_origin_folder / Path("models/weapons/arms/decompiled {}/{}".format(__crowbar_version__, SurvivorAttributes[survivor_destination]["fp_arms_name_list"]["mdl"].replace(".mdl", ".qc")))

	# Create and load the destination file handler
	handler_arms = QCFileHandler(decompiled_origin_path)
	handler_arms.load_file()

	origin_model_name_str = '$modelname "weapons\\arms\\{}"'.format(SurvivorAttributes[survivor_origin]["fp_arms_name_list"]["mdl"])
	destination_model_name_str = '$modelname "weapons\\arms\\{}"'.format(SurvivorAttributes[survivor_destination]["fp_arms_name_list"]["mdl"])

	handler_arms.content = handler_arms.content.replace(origin_model_name_str, destination_model_name_str)

	try:
		with decompiled_origin_path.open('w') as file:
			file.write(handler_arms.content)
			print("[+] The v_arms QC file strings has been replaced successfully.\n")
	except Exception as e:
		error_details = traceback.format_exc()
		print("[!] An error occurred during string replacement. {}.\nDetails:\n{}".format(e, error_details))

def copy_arms_origin_compiled_files():
	"""Copies the compiled arms files from the origin to the destination folder. 
	The function checks if the destination exists and then attempts to copy 
	the compiled model files from the source path. If the destination already contains files, 
	the copy operation is aborted with an appropriate message."""
	global SurvivorAttributes
	global survivor_origin_folder
	global survivor_destination_folder

	# Define source and destination paths
	source_path = survivor_origin_folder / Path("models/weapons/arms/decompiled {}/compiled {}/models".format(__crowbar_version__, __crowbar_version__))
	destination_path = survivor_destination_folder / Path("models/")

	# Check if the destination exists
	if destination_path.exists():
		try:
			# Copy the directory tree
			shutil.copytree(source_path, destination_path, dirs_exist_ok=True)
			print("[+] Copy from '{}' to '{}' was successful.".format(source_path, destination_path))
		except Exception as e:
			print("[!] Error during copy: {}. Press any key to try again.".format(e))
			pause()
			clear()
	else:
		print("[!] The destination '{}' already has files. Copy was not performed.".format(destination_path))

def delete_hunk_files():
	"""Deletes specific hunk-related model files from the decompiled destination path. 
	The function iterates through a predefined list of file names and removes each file if it exists. 
	Messages are printed to indicate whether the deletion was successful or if a file was not found."""
	global survivor_destination
	global SurvivorAttributes
	global survivor_destination_folder

	file_list = ["body1_model0.smd", "body1_model0_lod1.smd", 
				 "body2_model0.smd", "body2_model0_lod1.smd", 
				 "hunk.smd", "hunk_lod1.smd"]

	# Define decompiled destination path
	decompiled_destination_path = survivor_destination_folder / Path("models/survivors/decompiled {}".format(__crowbar_version__))

	# Iterate through the file list and delete each file
	for file_name in file_list:
		file_path = decompiled_destination_path / file_name
		if file_path.exists():
			file_path.unlink()
			print("[+] Deleted:", file_path)
		else:
			print("[!] File not found:", file_path)

def replace_survivor_qc_file_strings():
	"""Replaces specific strings in the QC file for the survivor's model based on the origin and destination survivors. 
	This function extracts and organizes animations, sequences, and collision joints from the origin survivor's QC file 
	and updates the destination QC file accordingly. It also handles errors, ensuring that missing files are reported, 
	and writes the modified content back to the destination file."""
	global survivor_origin
	global survivor_destination
	global SurvivorAttributes
	global survivor_destination_folder
	global survivor_origin_folder

	try:
		# Define decompiled destination path
		decompiled_destination_path = survivor_destination_folder / Path("models/survivors/decompiled {}/{}{}".format(
			__crowbar_version__, SurvivorAttributes[survivor_destination]["survivor_id"], ".qc"))
		# Define decompiled origin path
		decompiled_origin_path = survivor_origin_folder / Path("models/survivors/decompiled {}/{}{}".format(
			__crowbar_version__, SurvivorAttributes[survivor_origin]["survivor_id"], ".qc"))

		# Verify if destination and origin files exist before proceeding
		if not decompiled_destination_path.exists():
			raise FileNotFoundError("[!] Destination file not found: {}".format(decompiled_destination_path))

		if not decompiled_origin_path.exists():
			raise FileNotFoundError("[!] Origin file not found: {}".format(decompiled_origin_path))

		# Create and load the destination file handler
		handler_hunk = QCFileHandler(decompiled_destination_path)
		handler_hunk.load_file()

		# Create and load the source file handler
		handler_source = QCFileHandler(decompiled_origin_path)
		handler_source.load_file()
		handler_source.extract_sequences()
		handler_source.extract_animation()
		handler_source.extract_include_models()
		handler_source.extract_collisionjoints()
		handler_source.remove_variables_from_qc_file()

		# Extracts the content from the model after removing its variables
		extracted_model = handler_source.content

		# Get animations and sequences
		new_animations = handler_source.get_animations()
		sequences = handler_source.get_all_sequences()
		sequences_list = sequences.copy()

		# Arrange the sequences and obtain the sequence 'ragdoll'
		ragdoll_sequence, ordered_sequences = handler_source.organize_sequences()

		# Starts animation content
		new_contents = new_animations + "\n" if new_animations else ""
		new_contents += "\n\n" + list(ordered_sequences.values())[0] + "\n\n"
		extracted_model += new_contents

		# Replaces the $bodygroup-$sequence block in the target file
		handler_hunk.replace_var_from_start_to_end("$bodygroup \"", "$sequence", extracted_model)

		# Check and set 'ragdoll_sequence' if it does not exist
		if not ragdoll_sequence:
			ragdoll_sequence = ("ragdoll", "$sequence \"ragdoll\" {\n\"survivor_coach_anims\\ragdoll.smd\"\nactivity \"ACT_DIERAGDOLL\" 1\nfadein 0.2\nfadeout 0.2\nfps 30\nikrule \"rhand\" release contact 0 fakeorigin 0 0 0 fakerotate 0 0 0 floor 0 height 0 radius 0 range 0 0 0 0 target 0\nikrule \"lhand\" release contact 0 fakeorigin 0 0 0 fakerotate 0 0 0 floor 0 height 0 radius 0 range 0 0 0 0 target 1\nikrule \"rfoot\" release contact 0 fakeorigin 0 0 0 fakerotate 0 0 0 floor 0 height 0 radius 0 range 0 0 0 0 target 2\nikrule \"lfoot\" release contact 0 fakeorigin 0 0 0 fakerotate 0 0 0 floor 0 height 0 radius 0 range 0 0 0 0 target 3\nikrule \"ikclip\" release contact 0 fakeorigin 0 0 0 fakerotate 0 0 0 floor 0 height 0 radius 0 range 0 0 0 0 target 4\n}")

		# Replaces 'ragdoll' string in target file
		handler_hunk.replace_var_from_start_to_end("$sequence \"ragdoll\"", "}", ragdoll_sequence[1] + "\n\n")

		# Replaces $collisionjoints in the target file, if it exists
		new_collision_joints = handler_source.get_collision_joints()
		if new_collision_joints:
			handler_hunk.replace_var_from_start_to_end("$collisionjoints \"", "}", new_collision_joints)
		else:
			print("[!] Collision joints extraction failed.")

		# Prepare and add the contents of $includemodel
		include_models = ""
		new_sequences = ""

		# Added sequences to content, ignoring first index
		for i, sequence in enumerate(ordered_sequences.values()):
			if i > 0:
				new_sequences += sequence + "\n\n"

		include_models += new_sequences + handler_source.get_include_models()
		handler_hunk.add_content_above_includemodel(include_models)
		handler_hunk.content = re.sub(r'\n\s*\n', '\n\n', handler_hunk.content)

		# Write the modified content back to the destination file
		with decompiled_destination_path.open('w') as file:
			file.write(handler_hunk.content)
			print("\n[+] The QC file strings have been replaced successfully.\n")

	except Exception as e:
		error_details = traceback.format_exc()
		print("\n[!] An unexpected error occurred. {}.\nDetails:\n{}\n".format(e, error_details))

def copy_survivor_origin_decompiled_files():
	"""Copies decompiled files from the origin survivor's folder to the destination survivor's folder. 
	It identifies and filters files with specific extensions (.smd, .vrd, .vta) and includes the animations folder.
	The function ensures the destination directory exists before copying, and it handles both individual files 
	and directories. Finally, it confirms successful copying of all files."""
	global survivor_origin
	global survivor_destination
	global SurvivorAttributes
	global survivor_origin_folder
	global survivor_destination_folder

	# Define origin decompiled files path
	survivor_origin_decompiled_files_path = survivor_origin_folder / Path("models/survivors/decompiled {}".format(__crowbar_version__))

	# Define destination decompiled files path
	survivor_destination_decompiled_files_path = survivor_destination_folder / Path("models/survivors/decompiled {}".format(__crowbar_version__))

	# Define survivor anims folder
	survivor_anims_folder = SurvivorAttributes[survivor_origin]["survivor_anims_folder"]
	survivor_anims_folder_path = survivor_origin_decompiled_files_path / survivor_anims_folder

	# Filter files with extensions .smd, .vrd, .vta and include survivor_anims_folder
	filtered_origin_decompiled_files = list(survivor_origin_decompiled_files_path.glob('*.smd')) + \
									   list(survivor_origin_decompiled_files_path.glob('*.vrd')) + \
									   list(survivor_origin_decompiled_files_path.glob('*.vta')) + \
									   [survivor_anims_folder_path]

	# Ensure destination directory exists
	survivor_destination_decompiled_files_path.mkdir(parents=True, exist_ok=True)

	# Copy each file from origin to destination
	for file in filtered_origin_decompiled_files:
		# Check if it's a directory (in case of survivor_anims_folder)
		if file.is_dir():
			# Copy the entire directory
			destination_dir = survivor_destination_decompiled_files_path / file.name
			shutil.copytree(file, destination_dir, dirs_exist_ok=True)
			print("[+] Copy from '{}' to '{}' was successful.".format(file, destination_dir))
		else:
			# Copy individual files
			destination_file = survivor_destination_decompiled_files_path / file.name
			shutil.copy(file, destination_file)
			print("[+] Copy from '{}' to '{}' was successful.".format(file, destination_file))

	print("\n[+] All files copied successfully from '{}' to '{}'.\n".format(survivor_origin, survivor_destination))

def delete_decompiled_folder(folder, _type_):
	"""Deletes a specified decompiled folder (either destination or origin) and its contents. 
	The function takes a folder type (_type_) to determine whether to delete survivor-related or 
	arms-related folders. It checks for the existence of the specified folder before attempting to delete it,
	ensuring that the folder is indeed a directory. Upon successful deletion, it prints a confirmation message; 
	if the folder does not exist or is not a directory, it notifies the user accordingly."""
	global survivor_destination_folder
	global survivor_origin_folder

	survivor = ""
	folder_path = ""

	if folder == "destination":
		survivor = survivor_destination_folder
	elif folder == "origin":
		survivor = survivor_origin_folder

	if _type_ == "survivors":
		folder_path = survivor / Path("models/survivors/decompiled {}".format(__crowbar_version__))
	elif _type_ == "arms":
		folder_path = survivor / Path("models/weapons/arms/decompiled {}".format(__crowbar_version__))

	# Check if the folder exists
	if folder_path.exists() and folder_path.is_dir():
		# Remove the folder and its contents
		shutil.rmtree(folder_path)
		print("\n[+] Folder deleted successfully: {}\n".format(folder_path))
	else:
		print("\n[!] Folder not found or is not a directory: {}\n".format(folder_path))

def change_survivor_destination_folder_name():
	"""Changes the name of the survivor destination folder to a new name specified in the 
	'survivor_destination_final_folder' variable. It constructs the new folder path and attempts to rename 
	the current destination folder. If the renaming is successful, it updates the global variable to reflect 
	the new folder path and prints a success message. If a folder with the new name already exists, 
	it notifies the user, and it also handles any other exceptions that may occur during the renaming process."""
	global survivor_destination_final_folder
	global survivor_destination_folder
	global survivor_origin
	global survivor_destination

	try:
		# Sets the new path using the name in the survivor_destination_final_folder variable
		new_folder_path = survivor_destination_folder.parent / survivor_destination_final_folder

		# Rename the folder
		survivor_destination_folder.rename(new_folder_path)
		
		# Updates the global variable to the new path
		survivor_destination_folder = new_folder_path

		print("[+] Folder renamed successfully to '{}'.".format(survivor_destination_final_folder))
		print("[+] The Survivor {} has been Swapped to {}".format(survivor_origin, survivor_destination))
	except FileExistsError:
		print("[!] A folder with the name '{}' already exists.".format(survivor_destination_final_folder))
	except Exception as e:
		print("[!] An error occurred while renaming the folder: {}".format(e))

def load_settings(filename = r"./settings.json"):
	"""Load tool settings."""
	global vpk_executable
	global delete_folders_when_swap
	global close_crowbar_when_swap

	with open(filename, 'r') as file:
		settings = json.load(file)
		vpk_executable = settings["vpk_executable"]
		delete_folders_when_swap = settings["delete_folders_when_swap"]
		close_crowbar_when_swap = settings["close_crowbar_when_swap"]

	return settings

def compile_vpk():
	"""Compile to VPK and move the resulting file to 'Swapped_Survivors'"""
	global vpk_executable
	global survivor_destination_final_folder

	# Define source and target paths
	vpk_source_path = Path("Survivor_Swap/{}".format(survivor_destination_final_folder))

	# Convert to lowercase and add suffix ".vpk"
	vpk_file = Path("{}.vpk".format(str(vpk_source_path).lower()))

	# Sets the destination folder and destination file path
	target_folder = Path("Swapped_Survivors")
	target_file_path = target_folder / vpk_file.name  # Just the file name, no folder structure

	try:
		# VPK compilation
		print("\n[+] Compiling VPK...\n")
		subprocess.run([vpk_executable, vpk_source_path], check=True)
		print("\n[+] VPK compiled successfully!")

		# Ensure target folder exists
		target_folder.mkdir(parents=True, exist_ok=True)

		# Move the VPK file to the 'Swapped_Survivors' folder without including folder structure
		shutil.move(str(vpk_file), str(target_file_path))
		print("\n[+] VPK moved successfully to 'Swapped_Survivors'!")
	except subprocess.CalledProcessError as e:
		print("[!] Error compiling VPK: {}".format(e))
	except FileNotFoundError as e:
		print("[!] VPK file not found after compilation: {}".format(e))
	except Exception as e:
		print("\n[!] An unexpected error occurred: {}".format(e))

if __name__ == "__main__":
	main()