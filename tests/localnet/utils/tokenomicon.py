#!/usr/bin/env python3

import string
import yaml
import random
import subprocess
from math import ceil
from pathlib import Path
from tplr.logging import logger

def load_config():
    with open(Path("./subtensor_config.yaml"), 'r') as f:
        config = yaml.safe_load(f)
    return config

def load_wallet_info() -> dict:
    """Load wallet information from wallets.yaml file."""
    with open('wallets.yaml', 'r') as f:
        wallets = yaml.safe_load(f)
    return wallets

def open_wallet():
    wallets = load_wallet_info()
    # Retrieve admin wallet details, defaulting to an empty dictionary if not found
    admin_wallet = wallets['Admin']
    return admin_wallet

def calculate_faucet_calls(init_funding):
    base_amount = init_funding / 1000000000  # Convert to TAO
    calls = (base_amount / 1000) + 3  # Add 3 to ensure enough funds are transferred for fees and subnet registration
    return ceil(calls)

def admin_funding(config: dict, num_calls: int) -> None:
    admin_wallet = open_wallet()["wallet"][0]
    rpc_port = config['authorityNodes'][0]['subtensor_rpc_port']

    cmd = f"btcli wallet faucet --wallet.name {admin_wallet.get("wallet_name")} -v -p ./wallets --max-successes {str(num_calls)} --no-prompt --subtensor.chain_endpoint ws://127.0.0.1:{rpc_port}"       
    subprocess.run(cmd, shell=True, check=True)

def transfer_funds(rpc_port, wallet_info, amount):
    admin_wallet = open_wallet()
    cmd = f"btcli wallets transfer --wallet.name {admin_wallet["wallet_name"]} -d {wallet_info["ss58Address"]} -a {amount} --subtensor.chain_endpoint ws://127.0.0.1:{rpc_port} -p ./wallets --no_prompt --quiet"
    subprocess.run(cmd, shell=True, check=True)

def register_subnet(wallet_name, hotkey_name, wallet_path, rpc_port):
    characters = string.ascii_lowercase
    random_string = ''.join(random.choices(characters, k=5))

    cmd = f"btcli subnet create --wallet-name {wallet_name} --wallet-hotkey {hotkey_name} -p {wallet_path} --subnet-name \"{random_string}\" --github-repo \"https://github.com/opentensor/bittensor\" --subnet-contact \"{random_string}@{random_string}.{random_string}\" --subnet-url \"{random_string}.{random_string}\" --discord-handle \" \" --description \" \" --additional-info \"{random_string}\" --quiet --no_prompt --subtensor.chain_endpoint ws://127.0.0.1:{rpc_port}"
    subprocess.run(cmd, shell=True, check=True)

def register_hotkey(wallet_path, wallet_name, hotkey_name, netuid, rpc_port):
    cmd = f"btcli subnet register --wallet.name {wallet_name} -p {wallet_path} --wallet.hotkey {hotkey_name} --netuid {str(netuid)} --no-prompt --quiet --subtensor.chain_endpoint ws://127.0.0.1:{rpc_port}"
    subprocess.run(cmd, check=True)

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

def transfer_initial_funds(wallets: dict, rpc_port: int) -> None:
    """Transfer initial funds to validators and miners."""
    for wallet_type in ['Validators', 'Miners']:
        for wallet in wallets.get(wallet_type, []):
            if 'init_funding' in wallet:
                amount = int(wallet['init_funding'] / 1000000000)
                logger.info(f"Transferring {amount} TAO to {wallet['ss58Address']}")
                transfer_funds(rpc_port, wallet, amount)

def register_subnets(config: dict, wallets: dict,) -> None:
    """Register subnets for Admin and Validator wallets."""
    rpc_port = config['authorityNodes'][0]['subtensor_rpc_port']
    
    # Register subnet with Admin
    admin_wallet = wallets["Admin"]["wallet"][0]
    logger.info("Registering subnet 1 with Admin...")
    register_subnet(admin_wallet.get('wallet_name'), admin_wallet.get('hotkey_name'), Path("./wallets"), rpc_port)
    
    # Register subnet with Validator
    validator_wallet = wallets['Validators']["wallet"][0]
    logger.info("Registering subnet 2 with Validator...")
    register_subnet(validator_wallet.get('wallet_name'), validator_wallet.get('hotkey_name'), Path("./wallets"), rpc_port)

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

def ensure_validator_has_enough_balance(config: dict, wallets: dict) -> None:
    """Ensure validator has at least 100 TAO."""
    validator_wallet = wallets.get('Validators', [{}])[0]
    rpc_port = config['authorityNodes'][0]['subtensor_rpc_port']
    
    # Check balance
    check_balance_cmd = [
        'btcli', 'wallet', 'balance',
        f'--wallet.name={validator_wallet.get("wallet_name", "")}',
        f'--subtensor.chain_endpoint=ws://127.0.0.1:{rpc_port}'
    ]
    
    result = subprocess.run(check_balance_cmd, capture_output=True, text=True)
    balance = float(result.stdout.split()[0])
    
    if balance < 100:
        logger.info("Validator wallet has less than 100 TAO, adding more funds...")
        admin_funding(config, 1)  # Add one more faucet call
        transfer_cmd = [
            'btcli', 'wallets', 'transfer',
            f'--wallet.name={validator_wallet.get("wallet_name", "")}',
            f'-d={validator_wallet.get("ss58Address", "")}',
            '-a=100',
            f'--subtensor.chain_endpoint=ws://127.0.0.1:{rpc_port}',
            '--no_prompt',
            '--quiet'
        ]
        subprocess.run(transfer_cmd, check=True)

def stake_tao_for_validator(config: dict, wallets: dict) -> None:
    """Stake 100 TAO for validator on subnet 2."""
    validator_wallet = wallets.get('Validators', [{}])[0]
    rpc_port = config['authorityNodes'][0]['subtensor_rpc_port']
    
    stake_cmd = [
        'btcli', 'stake', 'add',
        f'--wallet.name={validator_wallet.get("wallet_name", "")}',
        f'--wallet.hotkey={validator_wallet.get("hotkey_name", "validator-hotkey")}',
        f'--subtensor.chain_endpoint=ws://127.0.0.1:{rpc_port}',
        '--amount=100',
        '--netuid=2',
        '-p=./wallets',
        '--unsafe',
        '--no-prompt',
        '--quiet'
    ]
    subprocess.run(stake_cmd, check=True)

def configure_chain(wallet_path: str):
    """Main function that coordinates all wallet configuration steps."""
    config, rpc_port = load_config_and_get_rpc_port()
    wallets = load_wallet_info()
    
    total_init_funding = calculate_total_initial_funding(wallets)
    num_calls = calculate_faucet_calls(total_init_funding)
    
    logger.info(f"Calling faucet {num_calls} times...")
    admin_funding(config, num_calls)
    
    transfer_initial_funds(wallets, rpc_port)
    register_subnets(config, wallets)

    # register all keys to subnet 2
    netuid = 2
    register_hotkeys(config, wallets, wallet_path, netuid)
    
    ensure_validator_has_enough_balance(config, wallets)
    stake_tao_for_validator(config, wallets)