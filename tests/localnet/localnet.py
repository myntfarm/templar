#!/usr/bin/env python3

import argparse
import subprocess
import torch.cuda.error
import yaml
import torch
from math import ceil
from pathlib import Path
from utils.tokenomicon import load_config, admin_faucet, admin_transfer_funds, configure_chain, validate_amount
from utils.manage_local_files import clone_github_repo, install_subnet_template, install_cubit
from utils.wallet_actions import validate_ss58, wallet_exsist
from utils.manage_subtensors import purge_chain_state, preflight_subtensor
from tplr.logging import logger

def parse_args():
    parser = argparse.ArgumentParser(description='Local Subtensor Network Manager')
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # Start command
    start_parser = subparsers.add_parser('start', help='Start the local Subensor network')
    start_parser.add_argument('--wallet-path', type=str, default='./wallets',
                            help='Path to store/read unencrypted wallets')
    
    # Stop command
    stop_parser = subparsers.add_parser('stop', help='Stop all subtensors')

    # Purge Local chain
    purge_parser = subparsers.add_parser('purge', help='Stop all subtensors and wipe local chain state')
    
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
    repo_config = Path("./utils/git_sources.yaml")
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

def main():
    args = parse_args()
    dependancy_flag_file = Path("./utils/.dependancy_installed_flag")

    if args.command == 'start':
        try:
            # Check if dependencies were already installed
            if not dependancy_flag_file.exists():
                logger.info("Dependencies flag not found. Beginning installation of dependencies...")

                if not clone_repos():
                    raise RuntimeError("Failed to clone repositories")   
            
                if not install_subnet_template():
                    raise RuntimeError("Failed to install subnet template")
                
                try:
                    if torch.cuda.device_count() > 0:
                        if not install_subnet_template():
                            raise RuntimeError("Failed to install cubit")
                except torch.cuda.error as e:
                    logger.info("Error calling CUDA devices. skipping cubit install.")

                # Launch Subtensor 
                preflight_subtensor(base_dir=Path("./repo_store/subtensor"), script_dir=Path("./repo_store/subtensor/scripts") , config_file=Path("./utils/subtensor_config.yaml"))

                # Create the flag file
                with open(dependancy_flag_file, 'a'):
                    pass
            else:
                # Launch Subtensor processes in background
                preflight_subtensor(base_dir=Path("./repo_store/subtensor"), script_dir=Path("./repo_store/subtensor/scripts"), config_file=Path("./utils/subtensor_config.yaml"))

            # Initialize wallets
            wallet_exsist(args.wallet_path)
            # Begin chain opertions
            configure_chain(args.wallet_path)

        except RuntimeError as e:
            logger.error(f"Error: {str(e)}")
            return

    elif args.command == 'stop':
        try:
            logger.info("Killing any existing nodes...")
            subprocess.run(['pkill', '-9', 'node-subtensor'], shell=True, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to kill existing nodes: {e}")

    elif args.command == 'purge':
        logger.info("Purging Subensor network...")
        purge_chain_state()


    elif args.command == 'fund':
        logger.info(f"funding {args.ss58} with {args.amount} Tao...")
        conf = load_config()
        rpc_port = conf['authorityNodes'][0]['subtensor_rpc_port']
        admin_faucet(args.wallet_path, ceil(args.amount/1000), rpc_port)
        admin_transfer_funds(rpc_port, args.ss58, args.amount, args.wallet_path)

if __name__ == "__main__":
    main()