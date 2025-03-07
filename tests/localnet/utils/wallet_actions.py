#!/usr/bin/env python3

import argparse
import subprocess
from tplr.logging import logger
import yaml
import time
import shutil
from pathlib import Path
from .manage_local_files import load_wallet_info, generate_wallets_yaml

def validate_ss58(address):
    """Validate that ss58 is a 48-character alphanumeric string."""
    if len(address) != 48 or not address.isalnum():
        raise argparse.ArgumentTypeError(
            "SS58 address is not 48 characters or contains invalid characters"
        )
    return address

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

def generate_new_wallets(wallet_path: str):
    wallets = load_wallet_info(wallet_path)

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


def get_coldsecretPhrase(name: str, wallet_path: str):
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
    wallets_yaml = wallet_path
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
    wallets_yaml = Path(wallet_path)
    if not wallets_yaml.exists():
        logger.info("Generating new wallets...")
        generate_wallets_yaml()
        time.sleep(2)
        generate_new_wallets(wallet_path)
    else:
        logger.info("Checking existing wallets...")
        if not check_wallets(wallet_path):
            logger.info("Missing wallets found, regenerating all wallets...")
            shutil.rmtree(wallet_path, ignore_errors=True)
            regenerate_wallets(wallet_path)



