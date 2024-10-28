import re
import os
from crowbar import __crowbar_version__

class QCFileHandler:
	def __init__(self, file_path):
		self.file_path = file_path
		self.sequences_dict = {}
		self.include_models = None
		self.collision_joints = []
		self.animations = []

	def load_file(self):
		"""Load the content of the QC file."""
		try:
			with open(self.file_path, 'r', encoding='utf-8') as file:
				self.content = file.read()
		except FileNotFoundError:
			print(f"[!] File {self.file_path} not found.")
			self.content = None

	# Methods for $sequence
	def extract_sequences(self):
		"""Extract $sequence blocks from QC file contents."""
		if self.content:
			# Find all matches of $sequence with name and block
			matches = re.finditer(r'(\$sequence\s+"(.*?)"\s*{)', self.content)

			for match in matches:
				# Get the name of the sequence and the starting index of the block
				sequence_name = match.group(2).strip()
				start_index = match.start(1)
				
				# Initialize key count
				open_brace_count = 1
				end_index = match.end(1)
				
				# Scroll through content to capture the entire block
				while open_brace_count > 0 and end_index < len(self.content):
					if self.content[end_index] == "{":
						open_brace_count += 1
					elif self.content[end_index] == "}":
						open_brace_count -= 1
					end_index += 1
				
				# Extract the complete block
				full_sequence_block = self.content[start_index:end_index].strip()
				
				# Add to dictionary if single block
				self.sequences_dict[sequence_name] = full_sequence_block
		else:
			print("[!] No content to process. Did you load the file?")

	def get_sequence_by_name(self, sequence_name):
		"""Retrieve the content of a specific $sequence by its name."""
		if sequence_name in self.sequences_dict:
			return self.sequences_dict[sequence_name]
		return False

	def get_all_sequences(self):
		"""Return all sequences as a dictionary."""
		return self.sequences_dict

	# Methods for $animation

	def extract_animation(self):
		"""Extract $animation blocks from the QC file content, removing duplicates based on the first animation name."""
		seen_names = set()  # Set to store unique names from the first string in quotes

		if self.content:
			# Regular expression to capture $animation blocks, with the first name in quotes
			matches = re.findall(r'(\$animation\s+"(.*?)"\s*".*?"\s*{.*?})', self.content, re.DOTALL)
			
			# Process each block of $animation
			unique_animations = []
			for match in matches:
				full_block, animation_name = match
				
				# Checks if the name of the first string has already been seen
				if animation_name not in seen_names:
					seen_names.add(animation_name)
					unique_animations.append(full_block)

			# Joins all unique blocks into a single string, with line breaks
			self.animations = '\n\n'.join(unique_animations)
		else:
			print("[!] No content to process. Did you load the file?")

	def get_animations(self):
		"""Return all $animation as a string."""
		return self.animations

	def print_animations(self):
		"""Print the extracted $animation."""
		if self.animations:
			print("[+] Animations:")
			print(self.animations)
		else:
			print("[!] No animations to display.")

	# Methods for $includemodel

	def extract_include_models(self):
		"""Extract $includemodel blocks and store them as a single string."""
		if self.content:
			matches = re.findall(r'\$includemodel\s+".*?"', self.content)
			if matches:
				# Junta todos os modelos incluídos em uma única string, com quebras de linha
				self.include_models = '\n'.join('{}'.format(model) for model in matches)
			else:
				self.include_models = ""
		else:
			print("[!] No content to process. Did you load the file?")

	def get_include_models(self):
		"""Return all $includemodel as a string."""
		return self.include_models

	def print_include_models(self):
		"""Print the extracted $includemodel."""
		if self.include_models:
			print("[+] Include Models:")
			print(self.include_models)
		else:
			print("[!] No include models to display.")

	# Methods for $collisionjoints

	def extract_collisionjoints(self):
		"""Extract $collisionjoints blocks from the QC file content."""
		if self.content:
			match = re.search(r'(\$collisionjoints\s+".*?"\s*{.*?})', self.content, re.DOTALL)

			if match:
				self.collision_joints = match.group(0).strip()
		else:
			print("[!] No content to process. Did you load the file?")

	def get_collision_joints(self):
		"""Return all collision joints as a list."""
		return self.collision_joints

	def print_collisionjoints(self):
		"""Print the extracted collision joints."""
		if self.collision_joints:
			print("[+] Collision Joints:")
			for joint in self.collision_joints:
				print(f"{joint}\n")
				print("=" * 50 + "\n")
		else:
			print("[!] No collision joints to display.")

	def remove_sequence_ragdoll_from_qc_file(self):
		"""Remove any $sequence ragdoll from the QC file content."""
		if self.content:
			# Remove the $sequence "ragdoll" block and its contents
			new_content = re.sub(r'\$sequence\s+"ragdoll"\s*{.*?}\s*', '', self.content, flags=re.DOTALL)

			# Normalize line breaks: ensure two or more consecutive newlines are replaced by a single newline
			new_content = re.sub(r'\n\s*\n+', '\n\n', new_content)

			# Update the temp_content
			self.content = new_content
		else:
			print("[!] No content to process. Did you load the file?")

	def remove_declaresequence_from_qc_file(self):
		"""Remove any $declaresequence from the QC file content."""
		if self.content:
			# Remove the $sequence "ragdoll" block and its contents
			new_content = re.sub(r'\$declaresequence\s+"\w"\s*{.*?}\s*', '', self.content, flags=re.DOTALL)

			# Normalize line breaks: ensure two or more consecutive newlines are replaced by a single newline
			new_content = re.sub(r'\n\s*\n+', '\n\n', new_content)

			# Update the temp_content
			self.content = new_content
		else:
			print("[!] No content to process. Did you load the file?")

	def extract_from_start_to_end(self, start, end):
		"""Extract everything from the first literal start block to the first end block."""
		if self.content:
			# Find the position of start
			start_index = self.content.find(start)
			if start_index != -1:
				# Find the position of end
				end_index = self.content.find(end, start_index)
				if end_index != -1:
					# Adjust end_index to include the closing brace
					end_index += len(end)

					# Extract the content between start and end
					extracted_content = self.content[start_index:end_index]
					print("[+] Content extracted successfully.")
					return extracted_content
				else:
					print("[!] No literal {} found after {}.".format(end, start))
			else:
				print("[!] No literal {} found.".format(start))
		else:
			print("[!] No content to process. Did you load the file?")

	def replace_var_from_start_to_end(self, start, end, new_content):
		"""Replace everything from the first literal start block to the first end block with new content."""
		if self.content:
			# Find the position of start
			start_index = self.content.find(start)
			if start_index != -1:
				# Find the position of end
				end_index = self.content.find(end, start_index)
				if end_index != -1:
					# Find the closing brace for the end block
					closing_brace_index = self.content.find("}", end_index)
					if closing_brace_index != -1:
						# Adjust closing_brace_index to include the closing brace
						closing_brace_index += 1

						# Replace the content between start and the closing brace of the end block
						self.content = (
							self.content[:start_index] + 
							new_content + 
							self.content[closing_brace_index:]
						)
						print("[+] Content replaced successfully from start to end.")
					else:
						print("[!] No closing brace found after end block.")
				else:
					print("[!] No literal {} found after {}.".format(end, start))
			else:
				print("[!] No literal {} found.".format(start))
		else:
			print("[!] No content to process. Did you load the file?")

	def extract_code_blocks(self, start_variable):
		"""Extract all blocks from a starting keyword (like $model) to their matching closing braces."""
		# List to store all found blocks
		blocks = []
		current_index = 0
		
		# Searches through all blocks until the end of the content
		while current_index < len(self.content):
			# Finds the position of the next starting variable
			start_index = self.content.find(start_variable, current_index)
			
			if start_index == -1:
				break  # If there are no more initial variables, exit the loop
			
			# Finds the first key opener after the initial variable
			brace_open_index = self.content.find("{", start_index)
			
			if brace_open_index == -1:
				print("No opening brace '{' found after the start variable.")
				break
			
			# Initialize key counter and move current index
			brace_count = 1
			current_index = brace_open_index + 1
			
			# Scroll through the content to find the corresponding block closure
			while brace_count > 0 and current_index < len(self.content):
				if self.content[current_index] == "{":
					brace_count += 1
				elif self.content[current_index] == "}":
					brace_count -= 1
				current_index += 1
			
			if brace_count == 0:
				# Adds the found block to the list
				block = self.content[start_index:current_index]
				blocks.append(block)
			else:
				print("No matching closing brace '}' found.")
				break
		
		# Returns all blocks found, separated by two line breaks
		return "\n\n".join(blocks) if blocks else None

	def add_content_above_includemodel(self, new_content):
		"""Add content above each $includemodel line, ensuring it's added only once."""
		# Split the content into lines for processing
		lines = self.content.splitlines()
		modified_lines = []
		added_content = False  # Flag to track if new content has been added

		for line in lines:
			if line.startswith("$includemodel") and not added_content:
				# Add the new content above the $includemodel line
				modified_lines.append(new_content)
				added_content = True  # Set the flag to indicate content was added
			
			# Add the original line
			modified_lines.append(line)

		# Join the modified lines back into a single string
		self.content = "\n".join(modified_lines)
		print("[+] Content added above the first $includemodel line.")

	def remove_variables_from_qc_file(self):
		"""Remove specific $variables from the QC file content, handling nested braces for $sequence, $animation, and $collisionjoints."""
		if self.content:
			# Remove comments and single-line variables
			self.content = self.content.replace("// Created by Crowbar {}".format(__crowbar_version__), "")
			self.content = re.sub(r'\$modelname[^\n]*\n', '', self.content)
			self.content = re.sub(r'\$declaresequence[^\n]*\n', '', self.content)
			self.content = re.sub(r'\$includemodel[^\n]*\n', '', self.content)

			# Built-in function to remove blocks with nested keys
			def remove_block(variable_name):
				result = []
				index = 0
				
				while True:
					# Find the next occurrence of the variable
					match = re.search(r'(\${}\s+".+?"\s*\{{)'.format(variable_name), self.content[index:])
					if not match:
						# If there are no more matches, add the rest of the content
						result.append(self.content[index:])
						break

					# Add content before found block
					result.append(self.content[index:index + match.start()])

					# Initialize key count and block indices
					start_index = index + match.start()
					end_index = start_index + match.end()
					open_brace_count = 1  # Count of '{' starts from 1 for already found starting key

					# Scroll through the content to find the correct closing
					while open_brace_count > 0 and end_index < len(self.content):
						if self.content[end_index] == "{":
							open_brace_count += 1
						elif self.content[end_index] == "}":
							open_brace_count -= 1
						end_index += 1

					# Update index to continue from end of current block
					index = end_index

				# Update content by removing variable blocks
				self.content = ''.join(result)

			# Remover blocos específicos
			remove_block(r'sequence')
			remove_block(r'animation')
			remove_block(r'collisionjoints')

			# Clear consecutive blank lines
			self.content = re.sub(r'\n\s*\n', '\n\n', self.content)
		else:
			print("[!] No content to process. Did you load the file?")

	def organize_sequences(self):
		"""Organizes sequences by identifying and separating the 'ragdoll' sequence from the rest.
		Returns the 'ragdoll' sequence as a tuple and a dictionary of other sequences, 
		ensuring the 'ragdoll' sequence is excluded from the ordered sequences."""

		# Initialize variables
		ragdoll_sequence = None
		ordered_sequences = {}

		# Go through the dictionary and search for the sequence containing 'ragdoll'
		for name, content in self.sequences_dict.items():
			if "ragdoll" in content.lower() and ragdoll_sequence is None:
				ragdoll_sequence = (name, content)  # Stores the string containing 'ragdoll'
			else:
				ordered_sequences[name] = content  # Add the rest to the dictionary

		# Returns the separated 'ragdoll' sequence and the dictionary of ordered_sequences without it
		return ragdoll_sequence, ordered_sequences