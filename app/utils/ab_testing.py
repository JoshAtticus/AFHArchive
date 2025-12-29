"""
A/B Testing utilities for AFHArchive
"""

import hashlib
import random
import secrets
from flask import session, request, current_app
from app import db
from app.models import ABTest, ABTestAssignment


def get_or_create_session_id():
    """Get or create a unique session identifier for A/B testing"""
    if 'ab_session_id' not in session:
        session['ab_session_id'] = secrets.token_hex(16)
    return session['ab_session_id']


def assign_to_test(test_name):
    """
    Assign a user to A/B test variant based on their session
    
    Args:
        test_name (str): Name of the A/B test
        
    Returns:
        str: 'control' or 'test' or None if test not active
    """
    # Get the test from database
    try:
        test = ABTest.query.filter_by(name=test_name, is_active=True).first()
        if not test:
            return None
        
        session_id = get_or_create_session_id()
        
        # Check if user already has an assignment for this test
        existing_assignment = ABTestAssignment.query.filter_by(
            session_id=session_id, 
            test_id=test.id
        ).first()
        
        if existing_assignment:
            return existing_assignment.variant
        
        # Create new assignment based on hash of session_id + test_name for consistency
        hash_input = f"{session_id}_{test_name}".encode('utf-8')
        hash_value = int(hashlib.md5(hash_input).hexdigest()[:8], 16)
        
        # Determine variant based on traffic percentage
        variant = 'test' if (hash_value % 100) < test.traffic_percentage else 'control'
        
        # Save assignment to database
        assignment = ABTestAssignment(
            session_id=session_id,
            test_id=test.id,
            variant=variant
        )
        
        db.session.add(assignment)
        db.session.commit()
        
        return variant
        
    except Exception as e:
        current_app.logger.error(f"Failed to assign/save A/B test assignment for {test_name}: {e}")
        db.session.rollback()
        
        # If the error is due to missing table, try to create it (last resort)
        if "no such table" in str(e) or "relation" in str(e) and "does not exist" in str(e):
            try:
                current_app.logger.info("Attempting to create missing ab_test_assignments table...")
                ABTestAssignment.__table__.create(db.engine)
                # Retry assignment once
                db.session.add(assignment)
                db.session.commit()
                return variant
            except Exception as e2:
                current_app.logger.error(f"Failed to create table/retry assignment: {e2}")
        
        # Fallback to control group if error persists
        return 'control'


def is_in_test_group(test_name):
    """
    Check if current user is in the test group for a specific test
    
    Args:
        test_name (str): Name of the A/B test
        
    Returns:
        bool: True if user is in test group, False otherwise
    """
    variant = assign_to_test(test_name)
    return variant == 'test'


def get_user_test_assignments():
    """
    Get all test assignments for the current user's session
    
    Returns:
        dict: Dictionary mapping test names to variants
    """
    session_id = get_or_create_session_id()
    
    assignments = db.session.query(ABTestAssignment, ABTest).join(
        ABTest, ABTestAssignment.test_id == ABTest.id
    ).filter(
        ABTestAssignment.session_id == session_id,
        ABTest.is_active == True
    ).all()
    
    return {test.name: assignment.variant for assignment, test in assignments}


def opt_out_of_test(test_name):
    """
    Opt user out of a specific A/B test by assigning them to control group
    
    Args:
        test_name (str): Name of the A/B test
        
    Returns:
        bool: True if successfully opted out, False otherwise
    """
    test = ABTest.query.filter_by(name=test_name, is_active=True).first()
    if not test:
        return False
    
    session_id = get_or_create_session_id()
    
    # Update or create assignment to control group
    assignment = ABTestAssignment.query.filter_by(
        session_id=session_id,
        test_id=test.id
    ).first()
    
    if assignment:
        assignment.variant = 'control'
    else:
        assignment = ABTestAssignment(
            session_id=session_id,
            test_id=test.id,
            variant='control'
        )
        db.session.add(assignment)
    
    try:
        db.session.commit()
        return True
    except Exception as e:
        current_app.logger.error(f"Failed to opt out of A/B test: {e}")
        db.session.rollback()
        return False


def get_test_stats(test_name):
    """
    Get statistics for an A/B test
    
    Args:
        test_name (str): Name of the A/B test
        
    Returns:
        dict: Statistics including total assignments, control/test counts
    """
    test = ABTest.query.filter_by(name=test_name).first()
    if not test:
        return None
    
    assignments = ABTestAssignment.query.filter_by(test_id=test.id).all()
    
    control_count = sum(1 for a in assignments if a.variant == 'control')
    test_count = sum(1 for a in assignments if a.variant == 'test')
    
    return {
        'test_name': test_name,
        'is_active': test.is_active,
        'traffic_percentage': test.traffic_percentage,
        'total_assignments': len(assignments),
        'control_count': control_count,
        'test_count': test_count,
        'created_at': test.created_at,
        'updated_at': test.updated_at
    }


def cleanup_old_assignments(days=30):
    """
    Clean up old A/B test assignments to prevent database bloat
    
    Args:
        days (int): Number of days to keep assignments
    """
    from datetime import datetime, timedelta
    
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    try:
        deleted_count = ABTestAssignment.query.filter(
            ABTestAssignment.assigned_at < cutoff_date
        ).delete()
        db.session.commit()
        
        current_app.logger.info(f"Cleaned up {deleted_count} old A/B test assignments")
        return deleted_count
    except Exception as e:
        current_app.logger.error(f"Failed to cleanup old A/B test assignments: {e}")
        db.session.rollback()
        return 0
