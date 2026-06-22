import json
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.db import models
from bookings.models import BookingMaster, ReceiptMaster
from accounts.models import Users

def cors_preflight(view_func):
    """Decorator to handle CORS preflight requests"""
    def wrapper(request, *args, **kwargs):
        if request.method == "OPTIONS":
            response = JsonResponse({})
            response["Access-Control-Allow-Origin"] = request.META.get("HTTP_ORIGIN", "*")
            response["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            response["Access-Control-Allow-Credentials"] = "true"
            return response
        return view_func(request, *args, **kwargs)
    return wrapper

@csrf_exempt
@cors_preflight
def login_api(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            username = data.get("username")
            password = data.get("password")
        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "message": "Invalid JSON"}, status=400)

        user = authenticate(username=username, password=password)

        if user is not None:
            login(request, user)
            return JsonResponse({
                "status": "success",
                "message": "Login successful",
                "user": {
                    "id": user.u_id,  # Using u_id as per models.py
                    "username": user.username,
                    "full_name": user.full_name,
                    "role": user.role
                }
            })
        else:
            return JsonResponse({"status": "error", "message": "Invalid credentials"}, status=401)
    
    return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)

@csrf_exempt
@cors_preflight
def me_api(request):
    if not request.user.is_authenticated:
        return JsonResponse({"status": "error", "message": "Unauthorized"}, status=401)
    
    user = request.user
    return JsonResponse({
        "status": "success",
        "user": {
            "id": user.u_id,
            "username": user.username,
            "role": user.role,
            "full_name": user.full_name,
            "email": user.email,
            "phone": user.phone
        }
    })

@csrf_exempt
@cors_preflight
def logout_api(request):
    if request.method == "POST":
        logout(request)
        return JsonResponse({"status": "success", "message": "Logged out successfully"})
    
    return JsonResponse({"status": "error", "message": "Method not allowed"}, status=405)


@csrf_exempt
@cors_preflight
def bookings_list_api(request):
    """Fetch bookings with complete user, property and payment details"""
    try:
        customer_id = request.GET.get("customer_id")
        
        if not customer_id:
            return JsonResponse({
                "status": "error",
                "message": "customer_id parameter is required"
            }, status=400)
        
        # Filter bookings with all related data
        bookings = BookingMaster.objects.filter(
            u_id=customer_id
        ).prefetch_related('items', 'u_id', 'p_id').order_by("-created_at")
        
        data = []
        for b in bookings:
            # Get user details
            user_details = None
            if b.u_id:
                user_details = {
                    "id": b.u_id.u_id,
                    "username": b.u_id.username,
                    "email": b.u_id.email,
                    "phone": b.u_id.phone,
                    "full_name": b.u_id.full_name,
                    "role": b.u_id.role,
                }
            
            # Get property/plot details from BookingItem
            properties = []
            total_booking_amount = 0
            for item in b.items.all():
                total_booking_amount += float(item.booking_amount) if item.booking_amount else 0
                properties.append({
                    "plot_no": item.plot_number,
                    "plot_name": item.plot_name,
                    "area_sqft": str(item.area_sqft),
                    "rate": str(item.rate),
                    "booking_amount": str(item.booking_amount),
                })
            
            booking_data = {
                # Booking ID and Number
                "id": b.b_id,
                "booking_no": b.booking_no,
                
                # User/Customer Personal Details
                "customer": {
                    "name": b.full_name,
                    "phone": b.phone,
                    "email": b.email,
                    "occupation": b.occupation,
                    "address": b.present_address,
                    "permanent_address": b.permanent_address,
                    "aadhar_number": b.aadhar_number,
                    "pin_code": b.pin_code,
                    "date_of_birth": b.date_of_birth.strftime("%Y-%m-%d") if b.date_of_birth else None,
                },
                
                # Property/Project Details
                "property": {
                    "project_name": b.p_id.name if b.p_id else "N/A",
                    "project_location": b.p_id.location if b.p_id else "N/A",
                    "location": b.location,
                    "plots": properties,
                },
                
                # Booking Amount Details
                "amount": {
                    "booking_amount": str(total_booking_amount),
                    "total_amount": str(total_booking_amount),  # Can be modified based on your logic
                },
                
                # Payment Details
                "payment": {
                    "payment_status": b.payment_status,
                    "payment_method": b.payment_method,
                    "next_payment_date": b.next_payment_date.strftime("%Y-%m-%d") if b.next_payment_date else None,
                },
                
                # Booking Dates
                "booking_date": b.booking_date.strftime("%Y-%m-%d") if b.booking_date else None,
                "created_at": b.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                
                # Linked User (from Users table)
                "user": user_details,
            }
            data.append(booking_data)
        
        return JsonResponse({
            "status": "success",
            "count": len(data),
            "bookings": data
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            "status": "error",
            "message": str(e)
        }, status=500)


@csrf_exempt
@cors_preflight
def payments_list_api(request):
    """Fetch all receipts/payments from receipt_master table with all fields"""
    try:
        # Optional filters
        booking_id = request.GET.get("booking_id")
        customer_name = request.GET.get("customer_name")
        payment_method = request.GET.get("payment_method")
        
        # Start with all receipts
        receipts = ReceiptMaster.objects.all()
        
        # Apply filters if provided
        if booking_id:
            receipts = receipts.filter(b_id=booking_id)
        if customer_name:
            receipts = receipts.filter(customer_name__icontains=customer_name)
        if payment_method:
            receipts = receipts.filter(payment_method=payment_method)
        
        # Order by most recent first
        receipts = receipts.order_by("-receipt_date", "-created_at")
        
        data = []
        for receipt in receipts:
            receipt_data = {
                # Receipt ID and Number
                "receipt_id": receipt.rm_id,
                "receipt_no": receipt.receipt_no,
                
                # Customer Details
                "customer": {
                    "name": receipt.customer_name,
                    "phone": receipt.phone,
                },
                
                # Booking Information
                "booking": {
                    "booking_id": receipt.b_id.b_id,
                    "booking_no": receipt.b_id.booking_no,
                },
                
                # Property Details
                "property": {
                    "plot_number": receipt.plot_number,
                },
                
                # Payment Amount Details
                "amount": {
                    "total_amount": str(receipt.total_amount),
                    "pay_amount": str(receipt.pay_amount),
                    "balance_amount": str(receipt.balance_amount),
                },
                
                # Payment Details
                "payment": {
                    "payment_method": receipt.payment_method,
                    "payment_details": receipt.payment_details,
                    "next_payment_date": receipt.next_payment_date.strftime("%Y-%m-%d") if receipt.next_payment_date else None,
                },
                
                # Dates
                "receipt_date": receipt.receipt_date.strftime("%Y-%m-%d"),
                "created_at": receipt.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }
            data.append(receipt_data)
        
        return JsonResponse({
            "status": "success",
            "count": len(data),
            "payments": data
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            "status": "error",
            "message": str(e)
        }, status=500)


@csrf_exempt
@cors_preflight
def user_profile_api(request, user_id=None):
    """Fetch user profile by ID or current user"""
    try:
        # If user_id is provided, fetch that user; otherwise fetch current user
        if user_id:
            try:
                user = Users.objects.get(u_id=user_id)
            except Users.DoesNotExist:
                return JsonResponse({"status": "error", "message": "User not found"}, status=404)
        else:
            if not request.user.is_authenticated:
                return JsonResponse({"status": "error", "message": "Unauthorized"}, status=401)
            user = request.user
        
        user_data = {
            # Primary Key
            "user_id": user.u_id,
            
            # Authentication Details
            "username": user.username,
            "email": user.email,
            
            # Personal Information
            "first_name": user.first_name,
            "last_name": user.last_name,
            "full_name": user.full_name,
            "phone": user.phone,
            
            # Role and Permissions
            "role": user.role,
            "is_staff": user.is_staff,
            "is_active": user.is_active,
            "is_superuser": user.is_superuser,
            
            # Metadata
            "created_by": user.created_by.u_id if user.created_by else None,
            "date_joined": user.date_joined.strftime("%Y-%m-%d %H:%M:%S"),
            "last_login": user.last_login.strftime("%Y-%m-%d %H:%M:%S") if user.last_login else None,
        }
        
        return JsonResponse({
            "status": "success",
            "user": user_data
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            "status": "error",
            "message": str(e)
        }, status=500)


@csrf_exempt
@cors_preflight
def users_list_api(request):
    """Fetch all users with filtering options"""
    try:
        # Optional filters
        role = request.GET.get("role")
        is_active = request.GET.get("is_active")
        search = request.GET.get("search")
        
        # Start with all users
        users = Users.objects.all()
        
        # Apply filters
        if role:
            users = users.filter(role=role)
        
        if is_active is not None:
            is_active_bool = is_active.lower() == 'true'
            users = users.filter(is_active=is_active_bool)
        
        if search:
            users = users.filter(
                models.Q(username__icontains=search) |
                models.Q(email__icontains=search) |
                models.Q(full_name__icontains=search) |
                models.Q(phone__icontains=search)
            )
        
        # Order by date joined (most recent first)
        users = users.order_by("-date_joined")
        
        data = []
        for user in users:
            user_data = {
                # Primary Key
                "user_id": user.u_id,
                
                # Authentication Details
                "username": user.username,
                "email": user.email,
                
                # Personal Information
                "first_name": user.first_name,
                "last_name": user.last_name,
                "full_name": user.full_name,
                "phone": user.phone,
                
                # Role and Permissions
                "role": user.role,
                "is_staff": user.is_staff,
                "is_active": user.is_active,
                "is_superuser": user.is_superuser,
                
                # Metadata
                "created_by": user.created_by.u_id if user.created_by else None,
                "date_joined": user.date_joined.strftime("%Y-%m-%d %H:%M:%S"),
                "last_login": user.last_login.strftime("%Y-%m-%d %H:%M:%S") if user.last_login else None,
            }
            data.append(user_data)
        
        return JsonResponse({
            "status": "success",
            "count": len(data),
            "users": data
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            "status": "error",
            "message": str(e)
        }, status=500)