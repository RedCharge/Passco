#!/usr/bin/env python3
"""
Favicon Generator for Past Questions App
This script generates all required favicon sizes from your logo.
"""

from PIL import Image, ImageDraw, ImageFont
import os
import sys

def generate_favicons_from_your_logo():
    """
    Generate all required favicon sizes from your specific logo
    """
     
    # Your logo path
    logo_path = r"C:\Users\user\pass_question_app\pass_questions\static\images\logos.jpg"
    
    print("🎨 Generating favicons from YOUR logo...")
    print("=" * 60)
    print(f"📍 Logo location: {logo_path}")
    print("=" * 60)
    
    # Check if logo exists
    if not os.path.exists(logo_path):
        print(f"❌ ERROR: Logo not found at: {logo_path}")
        print("\n📂 Please check the path exists:")
        print("1. Open File Explorer")
        print("2. Navigate to: C:\\Users\\user\\pass_question_app\\pass_questions\\static\\images\\")
        print("3. Verify 'logos.jpg' exists")
        print("\n💡 If the path is different, update the script with the correct path.")
        sys.exit(1)
    
    # Output directory - adjust based on your structure
    output_dir = r"C:\Users\user\pass_question_app\pass_questions\static"
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    print(f"📁 Output directory: {output_dir}")
    
    try:
        # Open your logo
        source_img = Image.open(logo_path)
        print(f"✅ Loaded logo: {source_img.format}, Size: {source_img.size}, Mode: {source_img.mode}")
        
        # Convert RGBA if needed (for PNG transparency support)
        if source_img.mode != 'RGBA':
            source_img = source_img.convert('RGBA')
            print("✅ Converted to RGBA for transparency support")
        
    except Exception as e:
        print(f"❌ Error loading logo: {e}")
        print("\n💡 Try converting your logo to PNG format for better results.")
        sys.exit(1)
    
    # Required sizes for different devices
    sizes = [
        (16, 16, 'favicon-16x16.png', 'Browser tab (small)'),
        (32, 32, 'favicon-32x32.png', 'Browser tab'),
        (180, 180, 'apple-touch-icon.png', 'iOS home screen'),
        (192, 192, 'android-chrome-192x192.png', 'Android home screen'),
        (512, 512, 'android-chrome-512x512.png', 'Splash screen'),
    ]
    
    # Generate each size
    generated_files = []
    for width, height, filename, description in sizes:
        try:
            # Resize image with high quality
            img = source_img.copy()
            
            # Calculate cropping to maintain aspect ratio
            img_ratio = img.width / img.height
            target_ratio = width / height
            
            if img_ratio != target_ratio:
                # Crop to match target ratio
                if img_ratio > target_ratio:
                    # Image is wider than target
                    new_width = int(img.height * target_ratio)
                    left = (img.width - new_width) // 2
                    img = img.crop((left, 0, left + new_width, img.height))
                else:
                    # Image is taller than target
                    new_height = int(img.width / target_ratio)
                    top = (img.height - new_height) // 2
                    img = img.crop((0, top, img.width, top + new_height))
            
            # Resize to exact dimensions
            img = img.resize((width, height), Image.Resampling.LANCZOS)
            
            # Save the image
            output_path = os.path.join(output_dir, filename)
            img.save(output_path, 'PNG', optimize=True, quality=95)
            
            generated_files.append(output_path)
            print(f"✅ {filename:30} ({width}x{height}) - {description}")
            
        except Exception as e:
            print(f"❌ Error generating {filename}: {e}")
    
    # Create .ico file (special format for favicon)
    try:
        ico_sizes = [(16, 16), (32, 32), (48, 48)]
        ico_images = []
        
        for size in ico_sizes:
            img = source_img.copy()
            
            # Crop to square for ICO
            if img.width != img.height:
                size_min = min(img.width, img.height)
                left = (img.width - size_min) // 2
                top = (img.height - size_min) // 2
                img = img.crop((left, top, left + size_min, top + size_min))
            
            img = img.resize(size, Image.Resampling.LANCZOS)
            ico_images.append(img)
        
        # Save as ICO
        ico_path = os.path.join(output_dir, 'favicon.ico')
        ico_images[0].save(ico_path, format='ICO', sizes=[(s[0], s[1]) for s in ico_sizes])
        generated_files.append(ico_path)
        print(f"✅ favicon.ico{'':24} (16x16,32x32,48x48) - Legacy browser support")
        
    except Exception as e:
        print(f"❌ Error generating favicon.ico: {e}")
    
    # Also create a copy in root static folder if different
    static_root = os.path.join(os.path.dirname(os.path.dirname(output_dir)), 'static')
    if output_dir != static_root and os.path.exists(static_root):
        try:
            print(f"\n📋 Copying to application static folder: {static_root}")
            for file in generated_files:
                if file.endswith('.png') or file.endswith('.ico'):
                    import shutil
                    dest = os.path.join(static_root, os.path.basename(file))
                    shutil.copy2(file, dest)
                    print(f"   📄 Copied: {os.path.basename(file)}")
        except Exception as e:
            print(f"   ⚠️  Note: {e}")
    
    print("\n" + "=" * 60)
    print(f"🎉 Successfully generated {len(generated_files)} favicon files!")
    print("\n📋 Generated files location:")
    for file in generated_files:
        file_size = os.path.getsize(file) / 1024
        print(f"   📍 {os.path.basename(file):25} ({file_size:.1f} KB)")
        print(f"      Path: {file}")
    
    return generated_files

def check_dependencies():
    """Check if required dependencies are installed"""
    try:
        from PIL import Image
        return True
    except ImportError:
        print("❌ Pillow library is not installed!")
        print("\n📦 Install it with:")
        print("   pip install pillow")
        return False

def verify_logo():
    """Verify the logo exists and show preview"""
    logo_path = r"C:\Users\user\pass_question_app\pass_questions\static\images\logos.jpg"
    
    if os.path.exists(logo_path):
        try:
            from PIL import Image
            img = Image.open(logo_path)
            print("✅ Logo found and valid!")
            print(f"   Size: {img.size[0]}x{img.size[1]} pixels")
            print(f"   Format: {img.format}")
            print(f"   Mode: {img.mode}")
            return True
        except Exception as e:
            print(f"⚠️  Logo exists but cannot be opened: {e}")
            return False
    else:
        print("❌ Logo not found!")
        print(f"\n📂 Expected at: {logo_path}")
        print("\n💡 Please verify:")
        print("1. The file 'logos.jpg' exists in that folder")
        print("2. The spelling is correct (case-sensitive)")
        print("3. You have read permissions")
        return False

def main():
    """Main function"""
    print("=" * 60)
    print("FAVICON GENERATOR - PAST QUESTIONS APP")
    print("=" * 60)
    
    # Check dependencies
    if not check_dependencies():
        sys.exit(1)
    
    # Verify logo exists
    print("\n🔍 Checking your logo...")
    if not verify_logo():
        print("\n❌ Cannot proceed without logo.")
        sys.exit(1)
    
    # Generate favicons
    try:
        generate_favicons_from_your_logo()
        
        print("\n" + "=" * 60)
        print("🎯 NEXT STEPS:")
        print("1. ✅ Favicons generated successfully!")
        print("2. Make sure your Flask app serves static files correctly")
        print("3. Run: python app.py")
        print("4. Open: http://localhost:5000")
        print("5. Check browser tab for favicon")
        print("6. On mobile: Use 'Add to Home Screen'")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Error during generation: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()