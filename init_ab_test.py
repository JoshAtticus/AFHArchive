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
        # 1. Direct Download Test
        existing_test = ABTest.query.filter_by(name='direct_download').first()
        
        if existing_test:
            print("Direct download A/B test already exists.")
        else:
            # Create the direct download A/B test
            test = ABTest(
                name='direct_download',
                description='Test direct downloads from direct.afharchive.xyz vs standard downloads',
                traffic_percentage=50,
                is_active=False
            )
            db.session.add(test)
            print("✅ Direct download A/B test created successfully!")

        # 2. Autoreviewer on Upload Test
        existing_ar_test = ABTest.query.filter_by(name='autoreviewer_on_upload').first()
        
        if existing_ar_test:
            print("Autoreviewer on upload A/B test already exists.")
        else:
            # Create the autoreviewer A/B test
            ar_test = ABTest(
                name='autoreviewer_on_upload',
                description='Automatically run AI autoreviewer on new uploads',
                traffic_percentage=50,
                is_active=False
            )
            db.session.add(ar_test)
            print("✅ Autoreviewer on upload A/B test created successfully!")
        
        try:
            db.session.commit()
            print("\nTests initialized. Activate them via admin panel.")
        except Exception as e:
            print(f"❌ Failed to save A/B tests: {e}")
            db.session.rollback()

if __name__ == '__main__':
    main()
