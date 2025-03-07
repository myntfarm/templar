#!/usr/bin/env python3

import subprocess
import sys
import os
from tplr.logging import logger
import yaml
from pathlib import Path

def load_wallet_info(wallet_path: str) -> dict:
    """Load wallet information from wallets.yaml file."""
    with open(wallet_path, 'r') as f:
        wallets = yaml.safe_load(f)
    return wallets

def load_config():
    with open("./utils/subtensor_config.yaml", 'r') as f:
        config = yaml.safe_load(f)
    return config

def clone_github_repo(repo_url: str, tag: str = None, branch: str = None, destination_path: str = ".."):
    """
    Clone a GitHub repository to a specified path and checkout a specific tag or branch if provided.
    
    Args:
        repo_url (str): URL of the GitHub repository to clone.
        tag (str, optional): Specific tag to checkout. Defaults to None.
        branch (str, optional): Specific branch to checkout. Defaults to None.
        destination_path (str, optional): Path where the repository will be cloned. 
                                         Defaults to the current working directory.
    """
    # Convert destination_path to an absolute path
    destination_path = os.path.abspath(destination_path)
    # repo_name = os.path.basename(repo_url).replace('.git', '')

    if not os.path.exists(destination_path):
        # If destination is just a filename, prepend current directory
        if os.path.dirname(destination_path) == '':
            parent_dir = os.getcwd()
            destination_path = os.path.join(parent_dir, os.path.basename(destination_path))
        else:
            parent_dir = os.path.dirname(destination_path)
        
        # Create the parent directories if they don't exist
        try:
            os.makedirs(parent_dir, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create directory: {e}")
            raise

        # Determine which reference (tag or branch) to checkout, prioritizing branch over tag
        if branch is not None:
            reference = branch
        elif tag is not None:
            reference = tag
        else:
            reference = None

        try:
            # Use git command to clone the repo and checkout the reference if specified
            git_args = [
                "git",
                "-C",
                parent_dir,
                "clone",
                repo_url,
                os.path.basename(destination_path),
            ]
            
            if reference:
                git_args.extend(["--branch", reference])
                
            subprocess.run(git_args, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to clone repository: {e}")
            raise
    else:
        logger.info("repo found skipping clone.")

def install_subnet_template() -> bool:
    """Install bittensor-subnet-template package"""
    package_path = Path('./repo_store/bittensor-subnet-template')
    if not package_path.exists():
        logger.error("Error: bittensor-subnet-template not found")
        return False
    
    logger.info("Installing subnet template...")
    subprocess.run(['python', '-m', 'pip', 'install', '-e', str(package_path)], check=True)
    return True

def build_binary(base_dir, features):
    """Build substrate binary with specified features."""
    try:
        logger.info("Checking rust install...")
        with subprocess.Popen("sh install_rust.sh", shell=True) as process:
            process.communicate()
        logger.info("Building substrate binary...")
        build_cmd = f"cargo build --workspace --profile=release --features \"{features}\" --manifest-path ./{base_dir}/Cargo.toml"
        subprocess.run(build_cmd, shell=True, check=True)
        logger.info("Binary compiled successfully")
        return True
    except subprocess.CalledProcessError as e:
            logger.error(f"Failed to build binary: {e}")
            sys.exit(1)

def build_chainspec(base_dir, script_dir):
    """Build chainspec for the specified configuration."""
    try:
        spec_path = os.path.join(script_dir, 'specs')
        if not os.path.exists(spec_path):
            logger.info(f"Creating directory {spec_path}")
            os.makedirs(spec_path, exist_ok=True)

        full_path = os.path.join(spec_path, 'local.json')

        logger.info("Building chainspec for local...")
        build_spec_cmd = f'{base_dir}/target/release/node-subtensor build-spec --disable-default-bootnode --raw --chain local > {full_path}'
        subprocess.run(build_spec_cmd, shell=True, check=True)
        logger.info(f"Chainspec built and output to file: {full_path}")
        return full_path
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to build chainspec: {e}")
        sys.exit(1)

def generate_node_keys(base_dir, authority_nodes, full_path):
    """Generate node keys for all authority nodes."""
    try:
        for node in authority_nodes:
            base_path = node.get('base-path', '/tmp/node')
            if not Path("{base_path}/chains/bittensor/network/secret_ed25519").exists:
                gen_key_cmd = f'{base_dir}/target/release/node-subtensor key generate-node-key --chain={full_path} --base-path {base_path}'
                logger.info(f"Generating key for {base_path}...")
                subprocess.run(gen_key_cmd, shell=True, check=True)

            else:
                logger.info("Node key found. Skipping generation.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to generate node keys: {e}")
        sys.exit(1)

def generate_wallets_yaml():
    config = {
        "Admin": {
            "wallet": [{
                "wallet_name": "Admin",
                "coldkey_secretPhrase": "",
                "hotkey_name": "AdminHot",
                "hotkey_secretPhrase": ""
            }]
        },
        "Validators": {
            "wallet": [{
                "wallet_name": "Validator",
                "coldkey_secretPhrase": "",
                "hotkey_name": "ValidatorHot",
                "hotkey_secretPhrase": "",
                "init_funding": 1101000000000
            }]
        },
        "Miners": {
            "wallet": [
                {
                    "wallet_name": "Miner1",
                    "coldkey_secretPhrase": "",
                    "hotkey_name": "Miner1Hot",
                    "hotkey_secretPhrase": "",
                    "init_funding": 1000000000000
                },
                {
                    "wallet_name": "Miner2", 
                    "coldkey_secretPhrase": "",
                    "hotkey_name": "Miner2Hot",
                    "hotkey_secretPhrase": "",
                    "init_funding": 1000000000000
                }
            ]
        }
    }

    with open('wallets.yaml', 'w') as f:
        yaml.dump(config, f)

def ensure_subtensor_binary(base_dir: str) -> str:
    """Ensure the Subensor binary exists and return its path."""
    binary_path = os.path.join(base_dir, 'target/release/node-subtensor')
    
    if not os.path.exists(binary_path):
        logger.info("Binary not found. Building...")

        
        with open(Path("./utils/subtensor_config.yaml"), 'r') as f:
            config = yaml.safe_load(f)
            features = config.get('binaryFeatures')
            build_binary(base_dir, features)
    
    return binary_path

def get_chainspec_path(base_dir: str, script_dir: str) -> str:
    """Get or create the chainspec file path."""
    spec_name = "local.json"
    spec_path = os.path.join(script_dir, 'specs', spec_name)
    
    if not os.path.exists(spec_path):
        logger.info(f"Chainspec {spec_name} not found. Building...")
        build_chainspec(base_dir, script_dir)
    
    return spec_path

def generate_node_keys_for_authority_nodes(
    base_dir: str,
    authority_nodes: list,
    chainspec_path: str
) -> None:
    """Generate node keys for all authority nodes if necessary."""
    for node in authority_nodes:
        base_path = node.get('base-path', '/tmp/node')
        key_file = os.path.join(base_path, 'node-key')
        
        if not os.path.exists(key_file):
            logger.info(f"Generating node key for {base_path}...")
            generate_node_keys(base_dir, [node], chainspec_path)



