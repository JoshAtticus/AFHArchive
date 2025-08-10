#!/usr/bin/env python3
"""
Initialize the direct download A/B test
Run this after the first app startup to create the initial test
"""

import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import ABTest

def main():
    app = create_app()
    
    with app.app_context():
        # Check if direct download test already exists
        existing_test = ABTest.query.filter_by(name='direct_download').first()
        
        if existing_test:
            print("Direct download A/B test already exists.")
            print(f"Status: {'Active' if existing_test.is_active else 'Inactive'}")
            print(f"Traffic: {existing_test.traffic_percentage}%")
            return
        
        # Create the direct download A/B test
        test = ABTest(
            name='direct_download',
            description='Test direct downloads from direct.afharchive.xyz vs standard downloads',
            traffic_percentage=50,
            is_active=False  # Start inactive until manually activated
        )
        
        try:
            db.session.add(test)
            db.session.commit()
            print("✅ Direct download A/B test created successfully!")
            print("📝 Test name: direct_download")
            print("🎯 Traffic: 50% to test group")
            print("⚡ Status: Inactive (activate via admin panel)")
            print("\nTo activate the test:")
            print("1. Start your Flask app")
            print("2. Go to /admin/ab-tests")
            print("3. Click 'Start' on the direct_download test")
        except Exception as e:
            print(f"❌ Failed to create A/B test: {e}")
            db.session.rollback()

if __name__ == '__main__':
    main()
