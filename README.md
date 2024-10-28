# L4D2 Survivor Swapper Tool

The L4D2 Survivor Swapper Tool was developed to simplify and expedite the process of converting survivor skins in the game *Left 4 Dead 2* (L4D2). Traditionally, this task required a time-consuming manual process, where each skin had to be individually adapted for each survivor.

## Developer

Developed by: **Sr.Caveira | 頭蓋骨 </> Dark'**  
Email: srcaveiraoficial@gmail.com  
Development date: 2024/10

## Description

### What the Tool Does

The L4D2 Survivor Swapper Tool allows users to quickly and efficiently convert skins from one survivor to another. For example, you can convert Coach's skin to Louis's, or vice versa, in just a few clicks. The tool automatically modifies the skin files, ensuring they are compatible with the desired survivor.

### How It Can Be Useful

This tool is especially beneficial for modders and players who want to personalize their gaming experience with unique and varied skins but do not want to spend hours making manual adjustments. With the Survivor Skin Converter, you can spend more time playing and less time modifying files, making skin customization a straightforward and accessible task.

## How to Use

### Prerequisites:
- Ensure the "Left 4 Dead 2 Authoring Tools" is installed;
- Ensure Python is installed on your system (or use the .exe version instead);
- Install the requirements.txt (or use the .exe version instead);
- Specify the path to the VPK executable in a file called `settings.json`.

### Important Notes:
- **Do not run the program twice without first clearing the "Survivor_Swap" folder.** If you encounter an error or the files are modified, the program may not function properly on subsequent executions.
- **Follow naming conventions:** Always name survivor folders in lowercase. For example, if converting an Ellis skin to Louis, name the skin folder as "ellis". Other valid names include `coach`, `francis`, `zoey`, etc.

### Steps to Use:
1. Place the folder of the survivor skin you wish to convert in the "Survivor_Swap" directory.
2. Setup the `settings.json` file where you can configure:
   - `close_crowbar_when_swap`: Whether to close Crowbar after conversion (true|false).
   - `delete_folders_after_swap`: Whether to delete folders after conversion (true|false).
   - `vpk_executable`: The path to the VPK executable (exe path).
3. Run the script `l4d2_survivor_swapper.py` or `l4d2_survivor_swapper.exe`.
4. **Origin Survivor:** Choose the survivor whose skin you are converting **from**.
5. **Destination Survivor:** Enter the survivor whose skin you are converting **to**.
6. **Final folder name input:** Name the output file. For example, after converting an Ellis skin with CJ's theme to Zoey, you could name it "CJ (Zoey)" or any valid file name.
7. **AddonInfo Configuration:** Configure `addoninfo.txt` by the input command, providing at least a name. Other fields are optional; to skip, just press enter with empty `` input.
   
### Troubleshooting:
- The tool is not perfect and might fail in certain situations. If it does, feel free to send the skin you tried to convert along with any error messages to my e-mail, and I will work on improving the tool based on the feedback, if it is the tool fault.
