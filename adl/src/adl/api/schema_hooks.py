def filter_endpoints(endpoints, ):
    filtered = []
    
    for (path, path_regex, method, callback) in endpoints:
        # Remove all but DRF API endpoints
        if path.startswith("/api/"):
            
            if path.startswith("/api/main"):
                continue
            
            filtered.append((path, path_regex, method, callback))
    
    return filtered
