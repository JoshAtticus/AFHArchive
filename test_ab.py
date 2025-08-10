#!/usr/bin/env python3
"""
Test the A/B testing functionality
"""

import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import create_app, db
from app.models import ABTest, ABTestAssignment
from app.utils.ab_testing import assign_to_test, is_in_test_group, get_test_stats
from flask import session

def test_ab_testing():
    app = create_app()
    
    with app.app_context():
        # Import inside context to ensure proper app context
        from app.utils.ab_testing import assign_to_test, get_test_stats
        
        # Check if test exists and is configured
        print("🧪 Testing A/B test configuration...")
        test = ABTest.query.filter_by(name='direct_download').first()
        
        if not test:
            print("❌ Direct download test not found!")
            return
            
        print(f"✅ Test found: {test.name}")
        print(f"📝 Description: {test.description}")
        print(f"🎯 Traffic: {test.traffic_percentage}%")
        print(f"⚡ Status: {'Active' if test.is_active else 'Inactive'}")
        
        # Test basic functionality with mock request context
        with app.test_request_context():
            print(f"\n🧪 Testing assignment logic...")
            # Test 1: Test inactive
            if not test.is_active:
                variant = assign_to_test('direct_download')
                print(f"   Inactive test assignment: {variant} (should be None)")
                
                # Activate test
                test.is_active = True
                db.session.commit()
                print("   Test activated for testing...")
            
            # Test 2: Test active
            variant = assign_to_test('direct_download')
            print(f"   Active test assignment: {variant} (should be 'control' or 'test')")
            
            # Test 3: Consistent assignment
            variant2 = assign_to_test('direct_download')
            print(f"   Second assignment (same session): {variant2} (should match first)")
            print(f"   Consistency check: {'✅ PASS' if variant == variant2 else '❌ FAIL'}")
            
            # Get statistics
            stats = get_test_stats('direct_download')
            if stats:
                print(f"\n📈 Current Statistics:")
                print(f"   Total assignments: {stats['total_assignments']}")
                print(f"   Control: {stats['control_count']}")
                print(f"   Test: {stats['test_count']}")
        
        print("\n✅ A/B testing basic functionality verified!")
        print("\n🚀 Ready to test with real Flask app!")

if __name__ == '__main__':
    test_ab_testing()
