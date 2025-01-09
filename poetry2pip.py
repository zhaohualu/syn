import re

def poetry_lock_to_requirements(poetry_lock_path, requirements_txt_path):
    with open(poetry_lock_path, "r") as lock_file:
        lines = lock_file.readlines()

    requirements = []
    package_name, version = None, None

    for line in lines:
        if line.startswith("[[package]]"):
            if package_name and version:
                requirements.append(f"{package_name}=={version}")
            package_name, version = None, None
        elif line.strip().startswith("name ="):
            package_name = re.search(r'"(.+)"', line).group(1)
        elif line.strip().startswith("version ="):
            version = re.search(r'"(.+)"', line).group(1)

    # Add the last package if not already added
    if package_name and version:
        requirements.append(f"{package_name}=={version}")

    # Write to requirements.txt
    with open(requirements_txt_path, "w") as req_file:
        req_file.write("\n".join(requirements))

# Replace these paths with your actual file paths
poetry_lock_path = "poetry.lock"
requirements_txt_path = "requirements.txt"

poetry_lock_to_requirements(poetry_lock_path, requirements_txt_path)
