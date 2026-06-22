"""
Custom CORS Middleware - No external dependencies required
Handles CORS for all API endpoints automatically
"""

from django.http import JsonResponse


class CorsMiddleware:
    """
    Middleware to handle CORS (Cross-Origin Resource Sharing) for all requests
    Allows requests from specified origins and handles preflight requests
    """
    
    # Allowed origins - add more as needed
    ALLOWED_ORIGINS = [
        "http://localhost:55380",      # Flutter web dev server
        "http://127.0.0.1:55380",
        "http://localhost:3000",        # React/Vue dev servers
        "http://127.0.0.1:3000",
        "http://localhost:8080",
        "http://127.0.0.1:8080",
        "http://localhost:5000",
        "http://127.0.0.1:5000",
        "http://localhost",
        "http://127.0.0.1",
    ]
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Handle preflight requests (OPTIONS method)
        if request.method == "OPTIONS":
            return self.preflight_response(request)
        
        # Get the actual response
        response = self.get_response(request)
        
        # Add CORS headers to all responses
        return self.add_cors_headers(request, response)
    
    def preflight_response(self, request):
        """Handle OPTIONS preflight requests"""
        response = JsonResponse({})
        return self.add_cors_headers(request, response)
    
    def add_cors_headers(self, request, response):
        """Add CORS headers to response"""
        origin = request.META.get("HTTP_ORIGIN", "")
        
        # Check if origin is allowed
        if origin in self.ALLOWED_ORIGINS or origin.startswith("http://localhost"):
            response["Access-Control-Allow-Origin"] = origin
        else:
            # Allow all origins in development (change for production)
            response["Access-Control-Allow-Origin"] = "*"
        
        response["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
        response["Access-Control-Allow-Headers"] = (
            "Content-Type, Authorization, X-CSRFToken, X-Requested-With, "
            "Accept, Accept-Encoding, Origin, Connection, User-Agent"
        )
        response["Access-Control-Allow-Credentials"] = "true"
        response["Access-Control-Expose-Headers"] = (
            "Authorization, Content-Type, X-CSRFToken, X-Total-Count"
        )
        response["Access-Control-Max-Age"] = "3600"
        
        return response