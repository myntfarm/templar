#!/usr/bin/env python3

import argparse
import subprocess
import yaml
import sys
import os
import shutil
import time
from math import ceil
from pathlib import Path
from utils.tokenomicon import load_config, admin_funding, transfer_funds, configure_chain
from tplr.logging import logger

def parse_args():
    parser = argparse.ArgumentParser(description='Local Subtensor Network Manager')
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # Start command
    start_parser = subparsers.add_parser('start', help='Start the local Subensor network')
    start_parser.add_argument('--purge', action='store_true',
                            help='Purge existing chain state and wallets')
    start_parser.add_argument('--wallet-path', type=str, default='./wallets',
                            help='Path to store/read unencrypted wallets')

    # Purge Local chain
    purge_parser = subparsers.add_parser('purge', help='Stop all subtensors and wipe local chain state')
    purge_parser.add_argument('--force', action='store_true',
                            help='Force purge without confirmation')
    
    # Fund command
    fund_parser = subparsers.add_parser('fund', help='Have Admin wallet send Tao to ss58 address')
    fund_parser.add_argument('--amount', type=validate_amount, required=True,
                        help='Amount in Tao to send.')
    fund_parser.add_argument('--ss58', type=validate_ss58, required=True,
                        help='ss58 address admin wallet will transfer tao too.')

    return parser.parse_args()

def clone_repos() -> bool:
    """Clone git repositories from git_sources.yaml.
    
    Returns:
        bool: True if successful, False otherwise
    """
    repo_config = Path('git_sources.yaml')
    if not repo_config.exists():
        logger.error("Error: git_sources.yaml not found")
        return False

    with open(repo_config, 'r') as f:
        repos = yaml.safe_load(f)

    for repo in repos:
        name = repo['repo_name']
        url = repo['repo_url']
        dest_path = Path(f"./repo_store/{name}")
        # Clone the repository
        logger.info(f"Cloning repository: {name}")
        if repo.get('release_tag'):
            # Use tag
           clone_github_repo(repo_url=url, destination_path=str(dest_path), tag=repo['release_tag'])
        else:
            # Use branch
            clone_github_repo(url, destination_path=str(dest_path), branch=repo['branch'])

    return True

def install_rust() -> bool:
    logger.info("*** Installing Rust")

    # Update package lists and install dependencies
    try:
        subprocess.run(["sudo", "apt-get", "update"], shell=True, check=True)
        subprocess.run([
            "sudo", "apt-get", "install", "-y",
            "cmake", "pkg-config", "libssl-dev", "git",
            "gcc", "build-essential", "clang", "libclang-dev",
            "protobuf-compiler", "rustc", ""
        ], check=True, shell=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Issue with install command trying without sudo...{e}")
        subprocess.run(["apt-get", "update"], check=True, shell=True)
        subprocess.run([
            "apt-get", "install", "-y",
            "cmake", "pkg-config", "libssl-dev", "git",
            "gcc", "build-essential", "clang", "libclang-dev",
            "protobuf-compiler", "rustc", ""
        ], check=True, shell=True)

    # Configure Rust
    subprocess.run(["rustup", "default", "stable"], check=True, shell=True)
    subprocess.run(["rustup", "update"], check=True, shell=True)
    subprocess.run([
        "rustup", "target", "add",
        "wasm32-unknown-unknown"
    ], check=True, shell=True)
    subprocess.run([
        "rustup", "toolchain", "install",
        "nightly"
    ], check=True, shell=True)
    subprocess.run([
        "rustup", "target", "add",
        "--toolchain", "nightly", "wasm32-unknown-unknown"
    ], check=True)
    subprocess.run([
        "rustup", "component", "add", "rust-src", 
        "--toolchain", "stable-x86_64-unknown-linux-gnu"
    ], check=True, shell=True)

    logger.info("*** Rust installation complete")

    return True

def install_subnet_template() -> bool:
    """Install bittensor-subnet-template package"""
    package_path = Path('./repo_store/bittensor-subnet-template')
    if not package_path.exists():
        logger.error("Error: bittensor-subnet-template not found")
        return False
    
    logger.info("Installing subnet template...")
    subprocess.run(['python', '-m', 'pip', 'install', '-e', str(package_path)], check=True)
    return True

def load_wallet_info() -> dict:
    """Load wallet information from wallets.yaml file."""
    with open('wallets.yaml', 'r') as f:
        wallets = yaml.safe_load(f)
    return wallets

def validate_amount(amount):
    """Validate that amount is a positive float."""
    try:
        value = float(amount)
        if value <= 0:
            raise ValueError
        return value
    except ValueError:
        raise argparse.ArgumentTypeError(
            "Amount must be a positive floating-point number."
        )

def validate_ss58(address):
    """Validate that ss58 is a 48-character alphanumeric string."""
    if len(address) != 48 or not address.isalnum():
        raise argparse.ArgumentTypeError(
            "SS58 address is not 48 characters or contains invalid characters"
        )
    return address

def build_binary(base_dir, features):
    """Build substrate binary with specified features."""
    try:
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

def clone_github_repo(repo_url: str, tag: str = None, branch: str = None, destination_path: str = "."):
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

def generate_wallets(wallet_path: str):
    wallets = load_wallet_info()

    coldkey_calls = []
    hotkey_calls = []

    # Generate btcli key commands
    for w in wallets["Admin"]["wallet"]:
        cold_cmd = f"btcli wallet new_coldkey --no-use-password --n_words 12 --quiet --wallet-name {w['wallet_name']} -p {wallet_path}"
        coldkey_calls.append(cold_cmd)
        hot_cmd = f"btcli wallet new-hotkey --no-use-password --n_words 12  --quiet --wallet-name {w['wallet_name']} --wallet-hotkey {w['hotkey_name']} -p {wallet_path}"
        hotkey_calls.append(hot_cmd)

    for w in wallets["Validators"]["wallet"]:
        cold_cmd = f"btcli wallet new_coldkey --no-use-password --n_words 12 --quiet --wallet-name {w['wallet_name']} -p {wallet_path}"
        coldkey_calls.append(cold_cmd)
        hot_cmd = f"btcli wallet new-hotkey --no-use-password --n_words 12  --quiet --wallet-name {w['wallet_name']} --wallet-hotkey {w['hotkey_name']} -p {wallet_path}"
        hotkey_calls.append(hot_cmd)

    for w in wallets["Miners"]["wallet"]:
        cold_cmd = f"btcli wallet new_coldkey --no-use-password --n_words 12 --quiet --wallet-name {w['wallet_name']} -p {wallet_path}"
        coldkey_calls.append(cold_cmd)
        hot_cmd = f"btcli wallet new-hotkey --no-use-password --n_words 12  --quiet --wallet-name {w['wallet_name']} --wallet-hotkey {w['hotkey_name']} -p {wallet_path}"
        hotkey_calls.append(hot_cmd)
        
    if len(coldkey_calls) > 0:
        for call in coldkey_calls:
            subprocess.run(call, shell=True, check=True)

    if len(hotkey_calls) > 0:
        for call in hotkey_calls:
            subprocess.run(call, shell=True, check=True)

    populate_generated_wallet_yaml(wallet_path)

    return wallets

def populate_generated_wallet_yaml(wallet_path: str):
    with open('wallets.yaml', 'r') as f:
        config = yaml.safe_load(f)

    config["Admin"]["wallet"][0]["coldkey_secretPhrase"] = get_coldsecretPhrase("Admin", wallet_path)
    config["Admin"]["wallet"][0]["hotkey_secretPhrase"] = get_hotsecretPhrase("Admin","AdminHot", wallet_path)
    config["Validators"]["wallet"][0]["coldkey_secretPhrase"] = get_coldsecretPhrase("Validator", wallet_path)
    config["Validators"]["wallet"][0]["hotkey_secretPhrase"] = get_hotsecretPhrase("Validator","ValidatorHot", wallet_path)

    for miner in config['Miners']['wallet']:
        miner['coldkey_secretPhrase'] = get_coldsecretPhrase(miner['wallet_name'], wallet_path)
        miner['hotkey_secretPhrase'] = get_hotsecretPhrase(miner['wallet_name'], miner['hotkey_name'], wallet_path)

    with open('wallets.yaml', 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

def regenerate_coldkey(name: str, wallet_path: str, coldkey_secretPhrase: str):
    """Regenerate a coldkey from existing secretPhrase"""
    cmd = f"btcli wallet regen-coldkey --wallet-name {name} -p {wallet_path} --mnemonic \"{coldkey_secretPhrase}\" --no-use-password --quiet"
    subprocess.run(cmd, shell=True, check=True)

def regenerate_hotkey(name: str, hotkey_name: str, wallet_path: str, hotkey_secretPhrase: str):
    """Regenerate a hotkey from existing secretPhrase"""
    cmd = f"btcli wallet regen_hotkey --wallet-name {name} --wallet-hotkey {hotkey_name} -p {wallet_path} --mnemonic \"{hotkey_secretPhrase}\" --no-use-password --quiet"
    subprocess.run(cmd, shell=True, check=True)

def regenerate_wallets(wallet_path: str):
    """Regenerate all wallets from existing secretPhrases in wallets.yaml"""
    config = load_wallet_info()
    
    # Regenerate Admin wallet
    for wallet in config["Admin"]["wallet"]:
        admin_name = wallet.get('wallet_name')
        admin_hotkey = wallet.get('hotkey_name')
        admin_coldsecretPhrase = wallet.get('coldkey_secretPhrase')
        admin_hotsecretPhrase = wallet.get('hotkey_secretPhrase')
        if admin_coldsecretPhrase:
            regenerate_coldkey(admin_name, wallet_path, admin_coldsecretPhrase)
        else:
            logger.error(f"Error: Issue detected with {admin_name} coldkey secretPhrase in {wallet_path}.")
        if admin_hotsecretPhrase:
            regenerate_hotkey(admin_name, admin_hotkey, wallet_path, admin_hotsecretPhrase)
        else:
            logger.error(f"Error: Issue detected with {admin_name} hotkey secretPhrase in {wallet_path}.")

    # Regenerate Validator wallet
    for wallet in config['Validators']['wallet']:
        validator_name = wallet.get('wallet_name')
        validator_hotkey = wallet.get('hotkey_name')
        validator_coldsecretPhrase = wallet.get('coldkey_secretPhrase')
        validator_hotsecretPhrase = wallet.get('hotkey_secretPhrase')
        if validator_coldsecretPhrase:
            regenerate_coldkey(validator_name, wallet_path, validator_coldsecretPhrase)
        else:
            logger.error(f"Error: issue detected {validator_name} coldkey secretPhrase in {wallet_path}")
        if validator_hotsecretPhrase:
            regenerate_hotkey(validator_name, validator_hotkey, wallet_path, validator_hotsecretPhrase)
        else:
            logger.error(f"Error: issue detected {validator_name} hotkey secretPhrase in {wallet_path}")

    # Regenerate Miner wallets
    for miner in config['Miners']['wallet']:
        miner_name = miner.get('wallet_name')
        miner_hotkey = miner.get('hotkey_name')
        miner_coldsecretPhrase = miner.get('coldkey_secretPhrase')
        miner_hotsecretPhrase = miner.get('hotkey_secretPhrase')
        if miner_coldsecretPhrase:
            regenerate_coldkey(miner_name, wallet_path, miner_coldsecretPhrase)
        else:
            logger.error(f"Error: issue detected {miner_name} coldkey secretPhrase in {wallet_path}")
        if miner_hotsecretPhrase:
            regenerate_hotkey(miner_name, miner_hotkey, wallet_path, miner_hotsecretPhrase)
        else:
            logger.error(f"Error: issue detected {miner_name} hotkey secretPhrase in {wallet_path}")

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

def get_coldsecretPhrase(name: str, wallet_path: str, ):
    secretPhrase_file = Path(wallet_path) / name / "coldkey"
    with open(secretPhrase_file, "r") as s:
        file = yaml.safe_load(s)
    return file["secretPhrase"]

def get_hotsecretPhrase(coldname: str, hotname: str, wallet_path: str, ):
    secretPhrase_file = Path(wallet_path) / coldname / "hotkeys" / hotname
    with open(secretPhrase_file, "r") as s:
        file = yaml.safe_load(s)
    return file["secretPhrase"]

def check_wallets(wallet_path: str) -> bool:
    wallets_yaml = Path('wallets.yaml')
    if not wallets_yaml.exists():
        logger.error("Wallets config file not found")
        return False

    with open(wallets_yaml, 'r') as f:
        config = yaml.safe_load(f)

    # Check each category
    for category in ['Admin', 'Validators', 'Miners']:
        category_config = config.get(category, {})
        
        # Safely access the 'wallet' key
        wallets = category_config.get('wallet', [])
        
        if not wallets:
            logger.error(f"No wallets found for {category}")
            return False

        for wallet in wallets:
            # Ensure each wallet has the necessary keys
            required_keys = ['wallet_name']
            if category != 'Admin':  # Add additional checks for other categories if needed
                required_keys.extend(['coldkey_secretPhrase', 'hotkey_secretPhrase'])
            
            # Check for all required keys
            for key in required_keys:
                if key not in wallet:
                    logger.error(f"Wallet under {category} missing key: {key}")
                    return False

    return True  # All checks passed

def wallet_exsist(wallet_path: str):
    wallets_yaml = Path('wallets.yaml')
    if not wallets_yaml.exists():
        logger.info("Generating new wallets...")
        generate_wallets_yaml()
        generate_wallets(wallet_path)
    else:
        logger.info("Checking existing wallets...")
        if not check_wallets(wallet_path):
            logger.info("Missing wallets found, regenerating all wallets...")
            shutil.rmtree(wallet_path, ignore_errors=True)
            regenerate_wallets(wallet_path)

def load_subtensor_config(config_file: str) -> dict:
    """Load and return Subtensor configuration from YAML file."""
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
        authority_nodes = config.get('authorityNodes', [])
        return {'config': config, 'authority_nodes': authority_nodes}

def ensure_subtensor_binary(base_dir: str) -> str:
    """Ensure the Subensor binary exists and return its path."""
    binary_path = os.path.join(base_dir, 'target/release/node-subtensor')
    
    if not os.path.exists(binary_path):
        logger.info("Binary not found. Building...")

        
        with open(Path("./subtensor_config.yaml"), 'r') as f:
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

def start_subtensor_node(
    base_dir: str,
    node_config: dict,
    chainspec_path: str
) -> subprocess.Popen:
    """Start a single Subensor node and return the process object."""
    binary_path = ensure_subtensor_binary(base_dir)
    
    base_path = node_config.get('base-path', '/tmp/node')
    port = node_config.get('subtensor_port', 30333)
    rpc_port = node_config.get('subtensor_rpc_port', 9944)
    flags = node_config.get(
        'subtensor_flags',
        '--validator --rpc-cors=all --allow-private-ipv4 --discover-local --unsafe-force-node-key-generation'
    )
    
    start_cmd = f"./{binary_path} --base-path {base_path} --chain ./{chainspec_path} --port {str(port)} --rpc-port {str(rpc_port)} {flags}"
    
    logger.info(f"Starting node with base path {base_path}...")
    return subprocess.Popen(start_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def launch_subtensor_nodes(
    base_dir: str,
    authority_nodes: list,
    chainspec_path: str
):
    """Launch Subensor nodes"""
    
    for node in authority_nodes:
        start_subtensor_node(base_dir, node, chainspec_path)
    logger.info("Subtensors Launched. Waiting 5 seconds for chain to become active.")
    time.sleep(5)
    

def launch_subtensor(
    base_dir: str,
    script_dir: str,
    config_file: str
) -> None:
    """Launch Subensor nodes and manage their lifecycle."""
    # Load configuration
    config_result = load_subtensor_config(config_file)
    authority_nodes = config_result["authority_nodes"]

    # Build Binary
    ensure_subtensor_binary(base_dir)
    
    # Get or create chainspec
    spec_path = get_chainspec_path(base_dir, script_dir)
    
    # Generate node keys if needed
    generate_node_keys_for_authority_nodes(
        base_dir,
        authority_nodes,
        spec_path
    )
    
    # Launch nodes and track processes
    launch_subtensor_nodes(base_dir, authority_nodes, spec_path)


def manage_chain_state(purge):
    """Manage chain state and cleanup."""
    if purge:
        # Kill any existing nodes
        try:
            logger.info("Killing any existing nodes...")
            subprocess.run(['pkill', '-9', 'node-subtensor'], check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to kill existing nodes: {e}")

        # Clean up node_pids.json if it exists
        if os.path.exists('node_pids.json'):
            try:
                os.remove('node_pids.json')
                logger.info("Removed node_pids.json")
            except Exception as e:
               logger.error(f"Failed to remove node_pids.json: {e}")

        # Reset Chainstate
        basePaths = load_subtensor_config(Path("./subtensor_config.yaml"))

        for node in basePaths["authority_nodes"]:
                chainstate = node.get("base-path")
                if os.path.exists(chainstate):
                    # Remove the directory and its contents
                    shutil.rmtree(chainstate)
                    logger.info(f"Directory '{chainstate}' has been removed successfully")
                else:
                    logger.error(f"The directory '{chainstate}' does not exist")

def main():
    args = parse_args()
    dependancy_flag_file = Path("./.dependancy_installed_flag")
    
    if args.command == 'start':
        try:
            # Check if dependencies were already installed
            if not dependancy_flag_file.exists():
                logger.info("Dependencies flag not found. Beginning installation of dependencies...")

                if not clone_repos():
                    raise RuntimeError("Failed to clone repositories")
            
                if not install_rust():
                    raise RuntimeError("Failed to install Rust dependencies")
            
                if not install_subnet_template():
                    raise RuntimeError("Failed to install subnet template")
            
                # Launch Subtensor 
                launch_subtensor(base_dir=Path("./repo_store/subtensor"), script_dir=Path("./repo_store/subtensor/scripts") , config_file=Path("./subtensor_config.yaml"))

                # Create the flag file
                with open(dependancy_flag_file, 'a'):
                    pass
            else:
                # Launch Subtensor processes in background
                launch_subtensor(base_dir=Path("./repo_store/subtensor"), script_dir=Path("./repo_store/subtensor/scripts"), config_file=Path("./subtensor_config.yaml"))

            # Initialize wallets
            wallet_exsist(args.wallet_path)
            # Begin chain opertions
            configure_chain()

        except RuntimeError as e:
            logger.error(f"Error: {str(e)}")
            return

    elif args.command == 'purge':
        logger.info("Purging Subensor network...")
        if not args.force:
            manage_chain_state(True)
        else:
            manage_chain_state(True, purge=True)

    elif args.command == 'fund':
        logger.info(f"funding {args.ss58} with {args.amount} Tao...")
        conf = load_config()
        admin_funding(conf, ceil(args.amount/1000))
        rpc_port = conf['authorityNodes'][0]['subtensor_rpc_port']
        transfer_funds(rpc_port, args.ss58, args.amount)

if __name__ == "__main__":
    main()