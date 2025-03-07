#!/usr/bin/env python3

import subprocess
import os
import time
import shutil
from tplr.logging import logger
import yaml
from pathlib import Path
from .manage_local_files import ensure_subtensor_binary, load_config, get_chainspec_path, generate_node_keys_for_authority_nodes

def load_subtensor_config(config_file: str) -> dict:
    """Load and return Subtensor configuration from YAML file."""
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
        authority_nodes = config.get('authorityNodes', [])
        return {'config': config, 'authority_nodes': authority_nodes}

def start_node(
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

def launch_all_subtensor_nodes(
    base_dir: str,
    authority_nodes: list,
    chainspec_path: str
):
    """Launch Subensor nodes"""
    
    for node in authority_nodes:
        start_node(base_dir, node, chainspec_path)
    logger.info("Subtensors Launched. Waiting 5 seconds for chain to become active.")
    time.sleep(5)

def preflight_subtensor(
    base_dir: str,
    script_dir: str,
    config_file: str
) -> None:

    # Load configuration
    config_result = load_config()
    authority_nodes = config_result["authorityNodes"]

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
    launch_all_subtensor_nodes(base_dir, authority_nodes, spec_path)

def purge_chain_state():
    """purge chain state and cleanup."""
    try:
        logger.info("Killing any existing nodes...")
        subprocess.run(['pkill', '-9', 'node-subtensor'], shell=True, check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to kill existing nodes: {e}")

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