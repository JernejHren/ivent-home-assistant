import os

files = [
    "custom_components/ivent/fan.py",
    "custom_components/ivent/sensor.py",
    "custom_components/ivent/switch.py",
    "custom_components/ivent/select.py",
    "custom_components/ivent/binary_sensor.py",
    "custom_components/ivent/button.py",
    "custom_components/ivent/text.py"
]

for file_path in files:
    if os.path.exists(file_path):
        with open(file_path, "r") as f:
            lines = f.readlines()
        
        # Determine if already added
        if any("PARALLEL_UPDATES" in line for line in lines):
            print(f"Skipping {file_path}, already has PARALLEL_UPDATES")
            continue
            
        new_lines = []
        for line in lines:
            if line.startswith("async def async_setup_entry"):
                new_lines.append("PARALLEL_UPDATES = 1\n\n")
            new_lines.append(line)
            
        with open(file_path, "w") as f:
            f.writelines(new_lines)
        print(f"Updated {file_path}")

