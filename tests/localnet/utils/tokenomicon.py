#!/usr/bin/env python3

import string
import yaml
import random
import subprocess
import argparse
from math import ceil
from pathlib import Path
from tplr.logging import logger
from manage_local_files import load_wallet_info, load_config

def get_admin_wallet(wallet_path: str):
    wallets = load_wallet_info(wallet_path)
    # Retrieve admin wallet details, defaulting to an empty dictionary if not found
    admin_wallet = wallets['Admin']["wallet"][0]
    return admin_wallet

def calculate_faucet_calls(init_funding: str):
    base_amount = init_funding / 1000000000  # Convert to TAO
    calls = (base_amount / 1000) + 3  # Add 3 to ensure enough funds are transferred for fees and subnet registration
    return ceil(calls)

def admin_faucet(wallet_path: str, num_calls: int, rpc_port: int) -> None:
    admin_wallet = get_admin_wallet(wallet_path)
    cmd = f"btcli wallet faucet --wallet.name {admin_wallet.get("wallet_name")} -v -p ./wallets --max-successes {str(num_calls)} --no-prompt --subtensor.chain_endpoint ws://127.0.0.1:{rpc_port}"       
    subprocess.run(cmd, shell=True, check=True)

def admin_transfer_funds(rpc_port: int, wallet_info: dict, amount: int, wallet_path:str):
    admin_wallet = get_admin_wallet(wallet_path)
    cmd = f"btcli wallets transfer --wallet.name {admin_wallet.get("wallet_name")} -d {wallet_info["ss58Address"]} -a {str(amount)} -p {wallet_path} --no_prompt --quiet --subtensor.chain_endpoint ws://127.0.0.1:{rpc_port} "
    subprocess.run(cmd, shell=True, check=True)

def register_subnet(wallet_name: str, hotkey_name: str, wallet_path: str, rpc_port: int):
    characters = string.ascii_lowercase
    random_string = ''.join(random.choices(characters, k=5))
    cmd = f"btcli subnet create --wallet-name {wallet_name} --wallet-hotkey {hotkey_name} -p {wallet_path} --subnet-name \"{random_string}\" --github-repo \"https://github.com/opentensor/bittensor\" --subnet-contact \"{random_string}@{random_string}.{random_string}\" --subnet-url \"{random_string}.{random_string}\" --discord-handle \" \" --description \" \" --additional-info \"{random_string}\" --quiet --no_prompt --subtensor.chain_endpoint ws://127.0.0.1:{rpc_port}"
    subprocess.run(cmd, shell=True, check=True)

def register_hotkey(wallet_path: str, wallet_name: str, hotkey_name: str, netuid: int, rpc_port: int):
    cmd = f"btcli subnet register --wallet.name {wallet_name} -p {wallet_path} --wallet.hotkey {hotkey_name} --netuid {str(netuid)} --no-prompt --quiet --subtensor.chain_endpoint ws://127.0.0.1:{str(rpc_port)}"
    subprocess.run(cmd, shell=True, check=True)

def load_config_and_get_rpc_port() -> tuple:
    """Load config file and extract RPC port from first authority node."""
    config = load_config()
    rpc_port = config['authorityNodes'][0]['subtensor_rpc_port']
    return config, rpc_port

def calculate_total_initial_funding(wallets: dict) -> float:
    """Calculate total initial funding needed for validators and miners."""
    fund = 0
    vali_fund = wallets["Validators"]["wallet"]
    miner_fund = wallets["Miners"]["wallet"]

    # Iterate through each validator's wallet and add init_funding to the total
    for w in vali_fund:
        fund += w.get("init_funding", 0)

    # Iterate through each miner's wallet and add init_funding to the total
    for we in miner_fund:
        fund += we.get("init_funding", 0)
        
    return fund

def transfer_initial_funds(wallets: dict, wallet_path: str, rpc_port: int) -> None:
    """Transfer initial funds to validators and miners."""
    for wallet_type in ['Validators', 'Miners']:
        for wallet in wallets[wallet_type]:
            if 'init_funding' in wallet:
                amount = int(wallet['init_funding'] / 1000000000)
                logger.info(f"Transferring {amount} TAO to {wallet['ss58Address']}")
                admin_transfer_funds(rpc_port, wallet, amount, wallet_path)

def register_init_subnets(config: dict, wallets: dict, wallet_path: str) -> None:
    """Register subnets for Admin and Validator wallets."""
    rpc_port = config['authorityNodes'][0]['subtensor_rpc_port']
    
    # Register subnet with Admin
    admin_wallet = wallets["Admin"]["wallet"][0]
    logger.info("Registering subnet 1 with Admin...")
    register_subnet(admin_wallet.get('wallet_name'), admin_wallet.get('hotkey_name'), wallet_path, rpc_port)
    
    # Register subnet with Validator
    validator_wallet = wallets['Validators']["wallet"][0]
    logger.info("Registering subnet 2 with Validator...")
    register_subnet(validator_wallet.get('wallet_name'), validator_wallet.get('hotkey_name'), wallet_path, rpc_port)

def register_hotkeys(config: dict, wallets: dict, wallet_path: str, netuid: int) -> None:
    """Register hotkeys for Validator and Miners."""
    rpc_port = config['authorityNodes'][0]['subtensor_rpc_port']
    
    # Register Validator hotkey
    validator_wallet = wallets['Validators']["wallet"][0]
    logger.info("Registering Validator hotkey to subnet 2...")
    register_hotkey(
        wallet_path,
        validator_wallet.get('wallet_name'),
        validator_wallet.get('hotkey_name'),
        netuid,
        rpc_port
    )
    
    # Register Miner hotkeys
    for miner in wallets.get('Miners', []):
        if 'init_funding' in miner:
            logger.info(f"Registering Miner {miner['ss58Address']} to subnet 2...")
            try:
                register_hotkey(
                    miner.get('wallet_name', ''),
                    miner.get('hotkey_name', 'miner-hotkey'),
                    rpc_port
                )
            except Exception as e:
                logger.error(f"Failed to register miner {miner['ss58Address']}: {str(e)}")

def check_wallet_balance(wallet_path: str, wallet_name: str, rpc_port: int, required_balance: float) -> bool:
    
    # Check balance
    check_balance_cmd = (f"btcli wallet balance -p {wallet_path} --wallet.name={wallet_name} --subtensor.chain_endpoint=ws://127.0.0.1:{str(rpc_port)}")
    
    result = subprocess.run(check_balance_cmd, capture_output=True, text=True)
    balance = float(result.stdout.split()[0])
    
    if balance < required_balance:
        logger.error(f"Wallet has {balance} but needs to have {required_balance}.")
        return False
    else:
        return True

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

def stake_tao(wallet_path: str, wallet_name: str, hotkey_name: str, netuid: int, stake_amount: float, rpc_port: int) -> None:
    stake_cmd = (f"btcli stake add --wallet.name={wallet_name} --wallet.hotkey={hotkey_name} --amount={str(stake_amount)} --netuid={netuid} -p={wallet_path} --unsafe --no-prompt --quiet --subtensor.chain_endpoint=ws://127.0.0.1:{rpc_port}")
    subprocess.run(stake_cmd, check=True)

def configure_chain(wallet_path: str):
    """Main function that coordinates all wallet configuration steps."""

    # get subtensor config and RPC port for local node
    config, rpc_port = load_config_and_get_rpc_port()
    # read wallets.yaml
    wallets = load_wallet_info(wallet_path)
    total_init_funding = calculate_total_initial_funding(wallets)
    num_calls = calculate_faucet_calls(total_init_funding)
    
    # call chain faucet to admin wallet
    logger.info(f"Calling faucet {num_calls} times...")
    admin_faucet(wallet_path, num_calls, rpc_port)
    
    # Send Tao to wallets to fund registrations and stake
    transfer_initial_funds(wallets, wallet_path, rpc_port)

    # Register subnets 1 & 2
    register_init_subnets(config, wallets, wallet_path)

    # register all keys to subnet 2
    netuid = 2
    register_hotkeys(config, wallets, wallet_path, netuid)

    # Have first validator Stake to netui 2
    vali_wallet = wallets["Validators"]["wallet"][0].get("wallet_name")
    vali_hotkey = wallets["Validators"]["wallet"][0].get("hotkey_name")
    vali_stake_netuid = 2
    stake_tao(wallet_path, vali_wallet, vali_hotkey, vali_stake_netuid, 100, rpc_port)