#!/usr/bin/env python
# ============================================================
# Script: set_admin.py
# Purpose: Set a specified user as administrator in the E-Bye system
# Usage: python set_admin.py [email@student.mmu.edu.my]
# ============================================================
#Eileen's part - Admin setup script for E-Bye system
import os
import sys
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Import database modules for database operations
from database import get_db, get_db_with_retry


# ============================================================
# Function: set_admin
# Description: Set a user as administrator by their email address
# @param {string} email - The email address of the user to promote to admin
# @returns {boolean} True if operation successful, False otherwise
# ============================================================
def set_admin(email):
    """Set the user with the specified email as an administrator"""
    try:
        # Establish database connection with retry mechanism
        db = get_db_with_retry()
        cur = db.cursor()
        
        # Check if user exists in the database
        cur.execute("SELECT id, username, email, is_admin FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        
        if not user:
            print(f"❌ User with email '{email}' not found!")
            return False
        
        # Check if user is already an administrator
        if user['is_admin'] == 1:
            print(f"⚠️ User {user['username']} ({email}) is already an admin!")
            return True
        
        # Update user's admin status to 1 (true/active)
        cur.execute("UPDATE users SET is_admin = 1 WHERE email = %s", (email,))
        db.commit()
        
        print(f"✅ Admin set successfully!")
        print(f"   User: {user['username']}")
        print(f"   Email: {email}")
        print(f"   Status: Now an administrator")
        
        # Clean up database connection
        cur.close()
        db.close()
        return True
        
    except Exception as e:
        print(f"❌ Error setting admin: {e}")
        # Ensure database connection is closed on error
        if 'db' in locals() and db:
            db.close()
        return False


# ============================================================
# Function: list_admins
# Description: Retrieve and display all current administrators
# @returns {list} List of admin user records, empty list on error
# ============================================================
def list_admins():
    """List all current administrators in the system"""
    try:
        # Establish database connection
        db = get_db_with_retry()
        cur = db.cursor()
        
        # Query all users with admin privileges
        cur.execute("SELECT id, username, email, is_admin FROM users WHERE is_admin = 1")
        admins = cur.fetchall()
        
        print("\n📋 Current Administrators:")
        print("-" * 50)
        for admin in admins:
            print(f"   ID: {admin['id']} | Username: {admin['username']} | Email: {admin['email']}")
        
        # Clean up database connection
        cur.close()
        db.close()
        return admins
        
    except Exception as e:
        print(f"❌ Error listing admins: {e}")
        return []


# ============================================================
# Main execution block
# Handles command-line arguments and executes admin setup
# ============================================================
if __name__ == "__main__":
    # Check if email was provided as command-line argument
    if len(sys.argv) > 1:
        email = sys.argv[1]
        print(f"Setting admin for: {email}")
        set_admin(email)
    else:
        # Use default email if no argument provided
        default_email = "EILEEN.KERK.HUI@student.mmu.edu.my"
        print(f"No email provided. Using default: {default_email}")
        set_admin(default_email)
    
    # Display the updated list of administrators
    list_admins()